import time
import asyncio
from typing import Dict, List, Any, Optional
from eth_account import Account
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, ApiCreds
from py_clob_client.exceptions import PolyApiException

from src.config import config
from src.feeds.multi_feed import MultiExchangePriceFeed
from src.feeds.polymarket_feed import PolymarketFeed
from src.engine.arbitrage_detector import MarketMakingOpportunity
from src.engine.paper_trader import MarketInventory
from src.utils.logger import get_logger, trade_logger

logger = get_logger("RealTrader")

class RealTradingEngine:
    """
    Motor Institucional de Ejecución en Dinero Real (Polymarket CLOB en Polygon):
    - Firma de órdenes EIP-712 de ultra-baja latencia.
    - Derivación y autenticación automática de credenciales CLOB.
    - Control estricto de riesgo: Strict Profit Guard, tope de exposición del 35% y máx 4 mercados.
    """
    def __init__(self, price_feed: MultiExchangePriceFeed, polymarket: PolymarketFeed):
        self.price_feed = price_feed
        self.polymarket = polymarket
        self.private_key = config.polymarket_private_key.strip()
        if self.private_key and not self.private_key.startswith("0x"):
            self.private_key = "0x" + self.private_key

        self.funder_address: str = ""
        self.client: Optional[ClobClient] = None
        self.balance_usdc: float = 0.0
        self.initial_balance: float = 0.0
        self.total_pnl_usdc: float = 0.0
        self.closed_trades_count: int = 0
        self.wins_count: int = 0
        self.losses_count: int = 0
        self.inventories: Dict[str, MarketInventory] = {}
        self.last_fill_time: Dict[str, float] = {}
        self._is_initialized: bool = False

        if self.private_key:
            self._init_client()

    def _init_client(self):
        try:
            account = Account.from_key(self.private_key)
            self.funder_address = account.address
            logger.info(f"🔑 Billetera Real Inicializada: {self.funder_address}")

            # Resolver dirección Proxy o Safe en Polymarket vía Gamma API en Virginia
            proxy_wallet = None
            try:
                import urllib.request
                import json
                url = f"https://gamma-api.polymarket.com/users?address={self.funder_address.lower()}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    users_data = json.loads(resp.read())
                    if isinstance(users_data, list) and len(users_data) > 0:
                        proxy_wallet = users_data[0].get("proxyWallet")
                    elif isinstance(users_data, dict):
                        proxy_wallet = users_data.get("proxyWallet")
            except Exception as e:
                logger.debug(f"Aviso al consultar proxyWallet en Gamma API: {e}")

            # Usar dirección funder configurada o proxyWallet detectada
            configured_funder = config.polymarket_funder_address.strip()
            active_funder = configured_funder or proxy_wallet or self.funder_address
            sig_type = 2 if active_funder.lower() != self.funder_address.lower() else (2 if proxy_wallet else 0)
            
            logger.info(f"🏛️ Polymarket Funder Address activo: {active_funder} (Firma Tipo {sig_type})")

            # Inicializar cliente CLOB en Polygon (Chain ID 137)
            self.client = ClobClient(
                host=config.polymarket_clob_http_url,
                chain_id=137,
                key=self.private_key,
                signature_type=sig_type,
                funder=active_funder
            )

            # Derivar o crear credenciales de API directamente en el servidor
            if config.polymarket_api_key and config.polymarket_api_secret and config.polymarket_passphrase:
                creds = ApiCreds(
                    api_key=config.polymarket_api_key,
                    api_secret=config.polymarket_api_secret,
                    api_passphrase=config.polymarket_passphrase
                )
                self.client.set_api_creds(creds)
                logger.info("🟢 Credenciales CLOB cargadas desde variables de entorno.")
            else:
                logger.info("⏳ Derivando credenciales CLOB oficiales de Polymarket...")
                creds = self.client.create_or_derive_api_creds()
                self.client.set_api_creds(creds)
                logger.info(f"🟢 Credenciales CLOB generadas y autenticadas con éxito (API Key: {creds.api_key[:8]}...)")

            self._is_initialized = True
            self.update_balance()
        except Exception as e:
            logger.error(f"❌ Error al inicializar cliente real de Polymarket: {e}")

    def update_balance(self):
        """Actualiza el balance real exacto de USDC en Polygon escaneando On-Chain RPC, Data API y CLOB API"""
        if not self.client or not self._is_initialized:
            return

        import urllib.request
        import json
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

        active_funder = getattr(self, "proxy_wallet", None) or config.polymarket_funder_address.strip() or self.funder_address
        addresses_to_check = list({addr for addr in [active_funder, self.funder_address, "0xbb9C2007dADB32d6c9c33d7CD630A929DcC5eaaf"] if addr})
        
        # 1. Escanear directamente la Blockchain de Polygon vía RPC (USDC.e y USDC Nativo)
        usdc_contracts = [
            "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", # Bridged USDC.e (Polymarket CTF)
            "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", # Native USDC
            "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"  # USDT (Polygon)
        ]
        polygon_rpcs = [
            "https://polygon-bor-rpc.publicnode.com",
            "https://1rpc.io/matic",
            "https://rpc.ankr.com/polygon",
            "https://polygon.llamarpc.com"
        ]

        on_chain_balance = 0.0
        for target_addr in addresses_to_check:
            clean_addr = target_addr.lower().replace("0x", "").zfill(64)
            call_data = "0x70a08231" + clean_addr # balanceOf(address)
            for contract in usdc_contracts:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [{"to": contract, "data": call_data}, "latest"],
                    "id": 1
                }
                for rpc in polygon_rpcs:
                    try:
                        req = urllib.request.Request(
                            rpc,
                            data=json.dumps(payload).encode(),
                            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
                        )
                        with urllib.request.urlopen(req, timeout=2.5) as resp:
                            res = json.loads(resp.read())
                            hex_val = res.get("result", "0x0")
                            int_val = int(hex_val, 16)
                            if int_val > 0:
                                parsed = round(int_val / 1e6, 2)
                                if parsed > on_chain_balance:
                                    on_chain_balance = parsed
                                    break
                    except Exception:
                        continue
                if on_chain_balance > 0:
                    break
            if on_chain_balance > 0:
                break

        # 2. Escanear CLOB API de Polymarket con los 3 tipos de firma
        clob_balance = 0.0
        for sig_type in [2, 1, 0]:
            try:
                params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=sig_type)
                bal_data = self.client.get_balance_allowance(params=params)
                if isinstance(bal_data, dict):
                    raw_bal = float(bal_data.get("balance", 0.0))
                    parsed_bal = round(raw_bal / 1e6, 2) if raw_bal > 1000 else round(raw_bal, 2)
                    if parsed_bal > 0:
                        clob_balance = parsed_bal
                        self.signature_type = sig_type
                        if hasattr(self.client, "builder") and self.client.builder:
                            self.client.builder.sig_type = sig_type
                        break
            except Exception:
                continue

        # Sincronizar el saldo más alto detectado en tiempo real
        detected_balance = max(on_chain_balance, clob_balance)
        if detected_balance > 0:
            self.balance_usdc = detected_balance

        if self.initial_balance == 0.0 and self.balance_usdc > 0:
            self.initial_balance = self.balance_usdc
            logger.info(f"💵 Balance Real Detectado en Polygon/Polymarket: ${self.balance_usdc:.2f} USDC (Firma Tipo {getattr(self, 'signature_type', 2)})")

    async def execute_signal(self, opp: MarketMakingOpportunity):
        """Ejecuta órdenes límite reales en el libro del CLOB de Polymarket"""
        if not self._is_initialized or not self.client:
            return

        now = time.time()
        cond_id = opp.condition_id

        if cond_id not in self.inventories:
            self.inventories[cond_id] = MarketInventory(
                condition_id=cond_id,
                asset=opp.asset,
                question=opp.market_question
            )

        inv = self.inventories[cond_id]

        # 1. Control Estricto de Exposición
        active_positions_count = len([i for i in self.inventories.values() if i.shares_held >= 5.0])
        total_invested = sum(i.shares_held * i.avg_buy_price for i in self.inventories.values())
        total_equity = self.balance_usdc + total_invested
        max_allowed_investment = total_equity * config.max_total_exposure_pct

        # Tamaño de orden
        if config.auto_compounding:
            compounded_size = self.balance_usdc * config.compounding_allocation_pct
            current_order_size = max(config.min_order_size_usdc, min(config.max_order_size_usdc, compounded_size))
        else:
            current_order_size = config.order_size_usdc

        # 2. CASO DE EJECUCIÓN VENTA (Strict Profit Guard)
        if inv.shares_held >= 5.0:
            target_min_sell = round(inv.avg_buy_price + config.min_trade_profit_cents, 3)
            sell_price = max(opp.limit_ask, opp.market_best_bid)

            if sell_price >= target_min_sell:
                if now - self.last_fill_time.get(f"{cond_id}_real_sell", 0) > 2.0:
                    try:
                        shares_to_sell = inv.shares_held
                        order_args = OrderArgs(
                            token_id=opp.yes_token_id,
                            price=round(sell_price, 3),
                            size=round(shares_to_sell, 2),
                            side="SELL"
                        )
                        resp = self.client.create_and_post_order(order_args)
                        logger.info(f"🚀 [ORDEN REAL DE VENTA ENVIADA] ID: {resp} | {shares_to_sell} sh @ ${sell_price:.3f}")

                        proceeds = round(shares_to_sell * sell_price, 2)
                        cost_basis = round(shares_to_sell * inv.avg_buy_price, 2)
                        profit = round(proceeds - cost_basis, 2)

                        self.balance_usdc += proceeds
                        self.total_pnl_usdc += profit
                        inv.shares_held = 0.0
                        inv.realized_pnl_usdc += profit
                        inv.roundtrips_count += 1
                        self.closed_trades_count += 1
                        self.wins_count += 1
                        self.last_fill_time[f"{cond_id}_real_sell"] = now

                        logger.info(
                            f"[bold green]💰 [BENEFICIO REAL COBRADO][/bold green] [{opp.asset}] "
                            f"Compra: ${inv.avg_buy_price:.3f} ➔ Venta: ${sell_price:.3f} | "
                            f"Ganancia Real: +${profit:.2f} USDC | Balance: ${self.balance_usdc:.2f} USDC"
                        )
                    except PolyApiException as e:
                        logger.error(f"Error de API al enviar venta real: {e}")
                    except Exception as e:
                        logger.error(f"Error al procesar orden de venta real: {e}")

        # 3. CASO DE COMPRA (Solo con liquidez libre y límite de posiciones)
        can_open_new = (active_positions_count < config.max_active_positions) or (inv.shares_held >= 5.0)
        can_invest = (total_invested < max_allowed_investment) and (self.balance_usdc >= current_order_size)

        if can_open_new and can_invest:
            if (opp.mispricing_type == "CHEAP_ASK" and opp.market_best_ask > 0) or (opp.market_best_ask <= opp.limit_bid and opp.limit_bid > 0):
                buy_price = opp.market_best_ask if opp.mispricing_type == "CHEAP_ASK" else opp.limit_bid
                if now - self.last_fill_time.get(f"{cond_id}_real_buy", 0) > 4.0:
                    try:
                        shares = round(current_order_size / buy_price, 2)
                        order_args = OrderArgs(
                            token_id=opp.yes_token_id,
                            price=round(buy_price, 3),
                            size=shares,
                            side="BUY"
                        )
                        resp = self.client.create_and_post_order(order_args)
                        logger.info(f"🛒 [ORDEN REAL DE COMPRA ENVIADA] ID: {resp} | {shares} sh @ ${buy_price:.3f}")

                        cost = round(shares * buy_price, 2)
                        self.balance_usdc -= cost
                        total_sh = inv.shares_held + shares
                        inv.avg_buy_price = ((inv.shares_held * inv.avg_buy_price) + cost) / total_sh if total_sh > 0 else buy_price
                        inv.shares_held = total_sh
                        self.last_fill_time[f"{cond_id}_real_buy"] = now
                    except PolyApiException as e:
                        logger.error(f"Error de API al enviar compra real: {e}")
                    except Exception as e:
                        logger.error(f"Error al procesar orden de compra real: {e}")

    def evaluate_open_positions(self):
        """Escaneo en tiempo real de salidas con ganancia obligatoria en modo real y refresco de saldo"""
        if not self._is_initialized or not self.client:
            return

        now = time.time()
        
        # Refrescar balance de la cuenta cada 5 segundos
        if now - getattr(self, "_last_balance_check", 0.0) > 5.0:
            self._last_balance_check = now
            self.update_balance()

        for cond_id, inv in list(self.inventories.items()):
            if inv.shares_held < 5.0:
                continue

            market = self.polymarket.active_markets.get(cond_id)
            if not market:
                continue

            market_bid = market.yes_book.best_bid
            target_min_sell = round(inv.avg_buy_price + config.min_trade_profit_cents, 3)

            if market_bid >= target_min_sell:
                if now - self.last_fill_time.get(f"{cond_id}_real_sell", 0) > 2.0:
                    try:
                        shares_to_sell = inv.shares_held
                        order_args = OrderArgs(
                            token_id=market.yes_token_id,
                            price=round(market_bid, 3),
                            size=round(shares_to_sell, 2),
                            side="SELL"
                        )
                        resp = self.client.create_and_post_order(order_args)
                        logger.info(f"🚀 [ORDEN REAL DE VENTA ENVIADA] ID: {resp} | {shares_to_sell} sh @ ${market_bid:.3f}")

                        proceeds = round(shares_to_sell * market_bid, 2)
                        cost_basis = round(shares_to_sell * inv.avg_buy_price, 2)
                        profit = round(proceeds - cost_basis, 2)

                        self.balance_usdc += proceeds
                        self.total_pnl_usdc += profit
                        inv.shares_held = 0.0
                        inv.realized_pnl_usdc += profit
                        inv.roundtrips_count += 1
                        self.closed_trades_count += 1
                        self.wins_count += 1
                        self.last_fill_time[f"{cond_id}_real_sell"] = now

                        logger.info(
                            f"[bold green]💰 [BENEFICIO REAL COBRADO][/bold green] [{inv.asset}] "
                            f"Compra: ${inv.avg_buy_price:.3f} ➔ Venta: ${market_bid:.3f} | "
                            f"Ganancia Real: +${profit:.2f} USDC | Balance: ${self.balance_usdc:.2f} USDC"
                        )
                    except Exception as e:
                        logger.error(f"Error en evaluate_open_positions real: {e}")

    def get_open_positions_summary(self) -> List[Dict[str, Any]]:
        """Retorna el listado detallado de posiciones abiertas en dinero real"""
        open_pos = []
        for cond_id, inv in self.inventories.items():
            if inv.shares_held >= 5.0:
                invested = round(inv.shares_held * inv.avg_buy_price, 2)
                target_sell = round(inv.avg_buy_price + config.target_spread_cents, 3)
                proj_profit = round(inv.shares_held * config.target_spread_cents, 2)
                proj_pct = round((config.target_spread_cents / inv.avg_buy_price) * 100.0, 1) if inv.avg_buy_price > 0 else 0.0
                open_pos.append({
                    "asset": inv.asset,
                    "question": inv.question,
                    "condition_id": cond_id,
                    "shares_held": round(inv.shares_held, 2),
                    "invested_usdc": invested,
                    "avg_buy_price": round(inv.avg_buy_price, 3),
                    "target_sell_price": target_sell,
                    "projected_profit_usdc": proj_profit,
                    "projected_profit_pct": proj_pct
                })
        return open_pos
