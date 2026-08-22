import time
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from src.config import config
from src.engine.arbitrage_detector import MarketMakingOpportunity
from src.feeds.polymarket_feed import PolymarketFeed
from src.feeds.multi_feed import MultiExchangePriceFeed
from src.utils.logger import get_logger, trade_logger

logger = get_logger("MarketMakerTrader")

@dataclass
class ActiveLimitOrder:
    order_id: str
    condition_id: str
    token_id: str
    side: str  # "BUY_LIMIT" (Bid) o "SELL_LIMIT" (Ask)
    price: float
    shares: float
    placed_ts: float

@dataclass
class MarketInventory:
    condition_id: str
    asset: str
    question: str
    shares_held: float = 0.0
    avg_buy_price: float = 0.0
    realized_pnl_usdc: float = 0.0
    roundtrips_count: int = 0

class PaperTradingEngine:
    """
    Motor Cuantitativo de Ejecución Maker (Órdenes Límite) y Captura Sistemática de Spread.
    - Coloca órdenes límite de compra (Bid) y venta (Ask) pasivas.
    - Captura el spread en cada ciclo completo de compra/venta sin pagar comisiones.
    - Explota precios erróneos (mispricings) cuando el mercado cotiza fuera del valor justo.
    """
    def __init__(self, polymarket_feed: PolymarketFeed, price_feed: MultiExchangePriceFeed):
        self.polymarket = polymarket_feed
        self.price_feed = price_feed
        self.balance_usdc: float = config.simulation_initial_balance
        self.initial_balance: float = config.simulation_initial_balance
        self.order_size: float = config.order_size_usdc
        self.latency_ms: int = config.simulated_network_latency_ms
        
        self.inventories: Dict[str, MarketInventory] = {}
        self.active_orders: Dict[str, ActiveLimitOrder] = {}
        self.closed_trades_count: int = 0
        self.wins_count: int = 0
        self.losses_count: int = 0
        self.total_pnl_usdc: float = 0.0
        self.last_fill_time: Dict[str, float] = {}

    async def execute_signal(self, opp: MarketMakingOpportunity):
        """Gestiona la colocación de órdenes límite y ejecuta fills cuando el mercado cruza nuestras cotizaciones"""
        now = time.time()
        cond_id = opp.condition_id

        if cond_id not in self.inventories:
            self.inventories[cond_id] = MarketInventory(
                condition_id=cond_id,
                asset=opp.asset,
                question=opp.market_question
            )

        inv = self.inventories[cond_id]

        # Simular latencia de colocación en Virginia (15ms)
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000.0)

        # Calcular tamaño de la orden con Interés Compuesto Automático
        if config.auto_compounding:
            compounded_size = self.balance_usdc * config.compounding_allocation_pct
            current_order_size = max(config.min_order_size_usdc, min(config.max_order_size_usdc, compounded_size))
        else:
            current_order_size = self.order_size

        # 1. CASO DE EXPLOTACIÓN DE PRECIO ERRÓNEO: Ask del mercado demasiado barato
        if opp.mispricing_type == "CHEAP_ASK" and opp.market_best_ask > 0:
            if now - self.last_fill_time.get(f"{cond_id}_buy", 0) > 3.0:
                shares = round(current_order_size / opp.market_best_ask, 2)
                cost = round(shares * opp.market_best_ask, 2)
                
                if self.balance_usdc >= cost and (inv.shares_held + shares) <= config.max_inventory_per_market:
                    self.balance_usdc -= cost
                    inv.shares_held += shares
                    inv.avg_buy_price = opp.market_best_ask
                    self.last_fill_time[f"{cond_id}_buy"] = now

                    logger.info(
                        f"🎯 [SNIPER FILL - PRECIO BARATO] [{opp.asset}] Compradas {shares} acciones YES @ {opp.market_best_ask:.3f} "
                        f"(Valor Justo: {opp.fair_price:.3f} | Descuento: +{opp.mispricing_edge*100:.1f}¢)"
                    )

        # 2. CASO DE EJECUCIÓN MAKER BID (Nuestra orden límite de compra fue ejecutada)
        elif opp.market_best_ask <= opp.limit_bid and opp.limit_bid > 0:
            if now - self.last_fill_time.get(f"{cond_id}_bid_fill", 0) > 4.0:
                shares = round(current_order_size / opp.limit_bid, 2)
                cost = round(shares * opp.limit_bid, 2)

                if self.balance_usdc >= cost and (inv.shares_held + shares) <= config.max_inventory_per_market:
                    self.balance_usdc -= cost
                    total_shares = inv.shares_held + shares
                    inv.avg_buy_price = ((inv.shares_held * inv.avg_buy_price) + cost) / total_shares if total_shares > 0 else opp.limit_bid
                    inv.shares_held = total_shares
                    self.last_fill_time[f"{cond_id}_bid_fill"] = now

                    logger.info(
                        f"📥 [MAKER BID FILL] [{opp.asset}] Retail vendió a nuestra orden límite de compra: {shares} acciones @ {opp.limit_bid:.3f} USDC"
                    )

        # 3. CASO DE EJECUCIÓN MAKER ASK (Nuestra orden límite de venta fue ejecutada - Ciclo Completado)
        if inv.shares_held >= 10.0 and (opp.market_best_bid >= opp.limit_ask or opp.mispricing_type == "EXPENSIVE_BID"):
            if now - self.last_fill_time.get(f"{cond_id}_ask_fill", 0) > 3.0:
                shares_to_sell = min(inv.shares_held, round(current_order_size / opp.limit_ask, 2))
                sell_price = max(opp.limit_ask, opp.market_best_bid)
                proceeds = round(shares_to_sell * sell_price, 2)
                cost_basis = round(shares_to_sell * inv.avg_buy_price, 2) if inv.avg_buy_price > 0 else round(shares_to_sell * opp.limit_bid, 2)
                
                profit = round(proceeds - cost_basis, 2)
                profit_pct = round((profit / cost_basis) * 100.0, 2) if cost_basis > 0 else 0.0

                self.balance_usdc += proceeds
                self.total_pnl_usdc += profit
                inv.shares_held -= shares_to_sell
                inv.realized_pnl_usdc += profit
                inv.roundtrips_count += 1
                self.closed_trades_count += 1

                if profit >= 0:
                    self.wins_count += 1
                    status_tag = "🟢 WIN"
                    color_tag = "[green]"
                else:
                    self.losses_count += 1
                    status_tag = "🔴 LOSS"
                    color_tag = "[red]"

                self.last_fill_time[f"{cond_id}_ask_fill"] = now

                # Registrar en CSV
                time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
                try:
                    trade_logger.log_trade({
                        "timestamp_entry": time_str,
                        "timestamp_exit": time_str,
                        "market_question": opp.market_question,
                        "token_id": opp.yes_token_id[:12],
                        "outcome": "YES_SPREAD_CYCLE",
                        "side": "MAKER_ROUNDTRIP",
                        "entry_price": f"{inv.avg_buy_price:.4f}",
                        "exit_price": f"{sell_price:.4f}",
                        "shares_count": f"{shares_to_sell:.2f}",
                        "size_usdc": f"{cost_basis:.2f}",
                        "pnl_usdc": f"{profit:.2f}",
                        "pnl_percentage": f"{profit_pct:.2f}%",
                        "exit_reason": "SPREAD_ROUNDTRIP_COMPLETED",
                        "lag_duration_ms": self.latency_ms,
                        "btc_price_entry": f"{self.price_feed.get_price(opp.asset):.2f}",
                        "btc_price_exit": f"{self.price_feed.get_price(opp.asset):.2f}",
                        "simulated_balance_after": f"{self.balance_usdc:.2f}"
                    })
                except Exception:
                    pass

                logger.info(
                    f"{color_tag}💰 [MAKER SPREAD CAPTURADO][/] [{opp.asset}] "
                    f"Compra: {inv.avg_buy_price:.3f} ➔ Venta: {sell_price:.3f} | "
                    f"Spread: +{sell_price - inv.avg_buy_price:.3f}¢ | "
                    f"Ganancia Neta: {color_tag}+${profit:.2f} USDC ({profit_pct:+.2f}%)[/] | "
                    f"Balance Total: ${self.balance_usdc:.2f} USDC"
                )

    def evaluate_open_positions(self):
        """En Market Making el inventario se gestiona dinámicamente mediante el modelo Avellaneda-Stoikov"""
        pass
