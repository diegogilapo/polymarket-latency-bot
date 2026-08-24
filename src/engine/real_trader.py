import time
import asyncio
from typing import Dict, List, Any, Optional
from eth_account import Account

try:
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.clob_types import OrderArgs, ApiCreds, AssetType, BalanceAllowanceParams
    from py_clob_client_v2.exceptions import PolyApiException
except ImportError:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, ApiCreds, AssetType, BalanceAllowanceParams
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
    - Firma de órdenes EIP-712 de ultra-baja latencia con soporte V2 oficial.
    - Derivación y autenticación automática de credenciales CLOB V2.
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

            # Resolver dirección Proxy o Safe en Polymarket vía Gamma API
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

            # Usar dirección funder y tipo de firma configurados
            configured_funder = config.polymarket_funder_address.strip()
            active_funder = configured_funder or proxy_wallet or self.funder_address
            sig_type = config.polymarket_signature_type
            
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
                logger.info("⏳ Derivando credenciales CLOB oficiales de Polymarket V2...")
                if hasattr(self.client, "create_or_derive_api_key"):
                    creds = self.client.create_or_derive_api_key()
                else:
                    creds = self.client.create_or_derive_api_creds()
                self.client.set_api_creds(creds)
                logger.info(f"🟢 Credenciales CLOB V2 generadas y autenticadas con éxito (API Key: {creds.api_key[:8]}...)")

            # Forzar sincronización de balance e indexación en el CLOB
            try:
                params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=sig_type)
                if hasattr(self.client, "update_balance_allowance"):
                    self.client.update_balance_allowance(params=params)
                logger.info("🟢 Sincronización e indexación de balance activada en Polymarket CLOB.")
            except Exception as e:
                logger.debug(f"Aviso al forzar indexación de balance: {e}")

            self._is_initialized = True
            self.update_balance()
        except Exception as e:
            logger.error(f"❌ Error al inicializar cliente real de Polymarket: {e}")

    def update_balance(self):
        """Actualiza el balance real exacto de USDC en Polygon escaneando Data API oficial de Polymarket, CLOB API y RPC"""
        if not self.client or not self._is_initialized:
            return

        import urllib.request
        import json

        candidate_addresses = list({addr.lower() for addr in [
            "0xbb9C2007dADB32d6c9c33d7CD630A929DcC5eaaf",
            config.polymarket_funder_address.strip(),
            getattr(self, "proxy_wallet", ""),
            self.funder_address
        ] if addr})
        
        detected_balance = 0.0

        # 1. Consultar CLOB API de Polymarket directamente con la firma configurada
        for sig_type in [config.polymarket_signature_type, 0, 2, 1]:
            try:
                params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=sig_type)
                bal_data = self.client.get_balance_allowance(params=params)
                if isinstance(bal_data, dict):
                    raw_bal = float(bal_data.get("balance", 0.0))
                    parsed_bal = round(raw_bal / 1e6, 2) if raw_bal > 1000 else round(raw_bal, 2)
                    if parsed_bal > 0:
                        detected_balance = parsed_bal
                        self.signature_type = sig_type
                        if hasattr(self.client, "builder") and self.client.builder:
                            self.client.builder.sig_type = sig_type
                        logger.info(f"📊 [CLOB API POLYMARKET] Saldo Detectado con Firma Tipo {sig_type}: ${detected_balance:.2f} USDC")
                        break
            except Exception:
                continue

        # 2. Consultar Data API y Gamma API oficiales de Polymarket para todas las direcciones
        if detected_balance == 0.0:
            for addr in candidate_addresses:
                endpoints = [
                    f"https://data-api.polymarket.com/portfolio?user={addr}",
                    f"https://data-api.polymarket.com/value?user={addr}",
                    f"https://data-api.polymarket.com/balances?user={addr}",
                    f"https://gamma-api.polymarket.com/users?address={addr}",
                    f"https://gamma-api.polymarket.com/profiles/{addr}"
                ]
                for url in endpoints:
                    try:
                        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=3.0) as resp:
                            data = json.loads(resp.read().decode())
                            if isinstance(data, dict):
                                cash = float(data.get("cash", 0.0) or 0.0)
                                pos_val = float(data.get("positionsValue", 0.0) or data.get("portfolioValue", 0.0) or data.get("value", 0.0) or data.get("total", 0.0) or 0.0)
                                total_val = cash + pos_val if (cash > 0 and pos_val > 0) else (pos_val or cash or float(data.get("balance", 0.0) or 0.0))
                                if total_val > detected_balance:
                                    detected_balance = round(total_val, 2)
                            elif isinstance(data, list):
                                for item in data:
                                    if isinstance(item, dict):
                                        val = float(item.get("value", 0.0) or item.get("amount", 0.0) or item.get("cash", 0.0) or item.get("balance", 0.0) or item.get("total", 0.0))
                                        if val > detected_balance:
                                            detected_balance = round(val, 2)
                                    elif isinstance(item, (int, float)):
                                        if float(item) > detected_balance:
                                            detected_balance = round(float(item), 2)
                            elif isinstance(data, (int, float)):
                                detected_balance = round(float(data), 2)
                            
                            if detected_balance > 0:
                                logger.info(f"📊 [DATA API POLYMARKET] Saldo Total Detectado para {addr[:10]}...: ${detected_balance:.2f} USD")
                                break
                    except Exception as e:
                        logger.debug(f"Aviso Data API: {e}")
                if detected_balance > 0:
                    break

        # 3. Consultar Contratos ERC20 de Polygon On-Chain (Native USDC / USDC.e / USDT)
        if detected_balance == 0.0:
            import httpx
            with httpx.Client(timeout=4.0) as http_client:
                for contract in ["0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"]:
                    for addr in candidate_addresses:
                        clean_addr = addr.lower().replace("0x", "").zfill(64)
                        call_data = "0x70a08231" + clean_addr
                        payload = {"jsonrpc": "2.0", "method": "eth_call", "params": [{"to": contract, "data": call_data}, "latest"], "id": 1}
                        for rpc in ["https://polygon.drpc.org", "https://1rpc.io/matic"]:
                            try:
                                resp = http_client.post(rpc, json=payload)
                                if resp.status_code == 200:
                                    res = resp.json()
                                    hex_val = res.get("result", "0x0")
                                    int_val = int(hex_val, 16)
                                    if int_val > 0:
                                        detected_balance = round(int_val / 1e6, 2)
                                        logger.info(f"📊 [ON-CHAIN POLYGON] Saldo Detectado en Contrato ({contract[:10]}...): ${detected_balance:.2f} USDC")
                                        break
                            except Exception:
                                continue
                        if detected_balance > 0:
                            break
                    if detected_balance > 0:
                        break

        if detected_balance > 0:
            self.balance_usdc = detected_balance

        if self.initial_balance == 0.0 and self.balance_usdc > 0:
            self.initial_balance = self.balance_usdc
            logger.info(f"💵 Balance Real Detectado en Polymarket: ${self.balance_usdc:.2f} USDC")

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
                        err_detail = getattr(e, "error_msg", None) or getattr(e, "message", str(e))
                        logger.error(f"❌ Error de API CLOB al enviar venta real: {err_detail} (Código: {getattr(e, 'status_code', None)})")
                    except Exception as e:
                        logger.error(f"Error inesperado al procesar orden de venta real: {e}")

        # 3. CASO DE COMPRA (Solo con liquidez libre y límite de posiciones)
        can_open_new = (active_positions_count < config.max_active_positions) or (inv.shares_held >= 5.0)
        can_invest = (total_invested < max_allowed_investment) and (self.balance_usdc >= current_order_size)

        if can_open_new and can_invest:
            buy_price = opp.limit_bid if (opp.limit_bid > 0 and opp.limit_bid <= opp.market_best_ask) else (opp.market_best_ask if opp.mispricing_type == "CHEAP_ASK" else 0.0)
            if buy_price > 0.01:
                if now - self.last_fill_time.get(f"{cond_id}_real_buy", 0) > 3.0:
                    try:
                        shares = max(5.0, round(current_order_size / buy_price, 1))
                        order_args = OrderArgs(
                            token_id=opp.yes_token_id,
                            price=round(buy_price, 3),
                            size=shares,
                            side="BUY"
                        )
                        resp = self.client.create_and_post_order(order_args)
                        logger.info(f"🛒 [ORDEN REAL DE COMPRA ENVIADA] ID: {resp} | {shares} sh @ ${buy_price:.3f} en [{opp.asset}]")

                        cost = round(shares * buy_price, 2)
                        self.balance_usdc = max(0.0, self.balance_usdc - cost)
                        total_sh = inv.shares_held + shares
                        inv.avg_buy_price = ((inv.shares_held * inv.avg_buy_price) + cost) / total_sh if total_sh > 0 else buy_price
                        inv.shares_held = total_sh
                        self.last_fill_time[f"{cond_id}_real_buy"] = now
                    except PolyApiException as e:
                        err_detail = getattr(e, "error_msg", None) or getattr(e, "message", str(e))
                        logger.error(f"❌ Error de API CLOB al enviar compra real: {err_detail} (Código: {getattr(e, 'status_code', None)})")
                    except Exception as e:
                        logger.error(f"Error inesperado al procesar orden de compra real: {e}")

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
