import time
import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional
from src.config import config
from src.engine.arbitrage_detector import ArbitrageSignal
from src.feeds.polymarket_feed import PolymarketFeed
from src.feeds.multi_feed import MultiExchangePriceFeed
from src.utils.logger import get_logger, trade_logger

logger = get_logger("ParityPaperTrader")

@dataclass
class ParityTradeRecord:
    asset: str
    market_question: str
    condition_id: str
    yes_ask: float
    no_ask: float
    combined_cost: float
    shares_count: float
    total_cost_usdc: float
    redemption_value_usdc: float
    net_profit_usdc: float
    profit_pct: float
    timestamp: float

class PaperTradingEngine:
    """
    Motor de Ejecución de Arbitraje Estructural de Paridad Binaria (100% Risk-Free).
    Compra simultáneamente acciones YES + NO cuando la suma de costos es menor a 1.00 USDC,
    garantizando un rendimiento neto positivo inmediato con 0 riesgo direccional.
    """
    def __init__(self, polymarket_feed: PolymarketFeed, price_feed: MultiExchangePriceFeed):
        self.polymarket = polymarket_feed
        self.price_feed = price_feed
        self.balance_usdc: float = config.simulation_initial_balance
        self.initial_balance: float = config.simulation_initial_balance
        self.order_size: float = config.order_size_usdc
        self.latency_ms: int = config.simulated_network_latency_ms
        
        self.open_positions: Dict[str, Any] = {}
        self.closed_trades_count: int = 0
        self.wins_count: int = 0
        self.losses_count: int = 0
        self.total_pnl_usdc: float = 0.0

    async def execute_signal(self, signal: ArbitrageSignal):
        """Ejecuta la compra dual YES + NO y canjea la paridad garantizada al 1.00 USDC"""
        if self.balance_usdc < self.order_size:
            logger.warning(f"⚠️ Balance virtual insuficiente (${self.balance_usdc:.2f} USDC)")
            return

        # Simular latencia de colocación en Virginia (15ms)
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000.0)

        market = self.polymarket.active_markets.get(signal.condition_id)
        if not market:
            return

        current_yes_ask = market.yes_book.best_ask
        current_no_ask = market.no_book.best_ask
        current_combined = current_yes_ask + current_no_ask

        # Verificar que el margen de arbitraje siga existiendo tras la latencia
        if current_combined > config.max_combined_ask_sum:
            logger.info(f"⚡ [LATENCIA PERDIDA] Los Asks subieron (YES {current_yes_ask:.3f} + NO {current_no_ask:.3f} = ${current_combined:.3f})")
            return

        # Calcular número de pares completos a comprar
        shares_to_buy = round(self.order_size / current_combined, 2)
        total_cost = round(shares_to_buy * current_combined, 2)
        redemption_value = round(shares_to_buy * 1.00, 2)
        net_profit = round(redemption_value - total_cost, 2)
        profit_pct = round((net_profit / total_cost) * 100.0, 2)

        # Actualizar balance y estadísticas atómicamente
        self.balance_usdc += net_profit
        self.total_pnl_usdc += net_profit
        self.closed_trades_count += 1
        self.wins_count += 1

        now = time.time()
        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))

        # Registrar en CSV
        try:
            trade_logger.log_trade({
                "timestamp_entry": time_str,
                "timestamp_exit": time_str,
                "market_question": signal.market_question,
                "token_id": f"{signal.yes_token_id[:6]}_{signal.no_token_id[:6]}",
                "outcome": "YES+NO_PARITY",
                "side": "DUAL_BUY",
                "entry_price": f"{current_combined:.4f}",
                "exit_price": "1.0000",
                "shares_count": f"{shares_to_buy:.2f}",
                "size_usdc": f"{total_cost:.2f}",
                "pnl_usdc": f"{net_profit:.2f}",
                "pnl_percentage": f"{profit_pct:.2f}%",
                "exit_reason": "PARITY_ARBITRAGE_REDEEM",
                "lag_duration_ms": self.latency_ms,
                "btc_price_entry": f"{self.price_feed.get_price(signal.asset):.2f}",
                "btc_price_exit": f"{self.price_feed.get_price(signal.asset):.2f}",
                "simulated_balance_after": f"{self.balance_usdc:.2f}"
            })
        except Exception as e:
            logger.debug(f"Error escribiendo CSV: {e}")

        logger.info(
            f"[bold green]🟢 PARITY ARBITRAGE ARB[/bold green] [{signal.asset}] "
            f"YES @ {current_yes_ask:.3f} + NO @ {current_no_ask:.3f} = ${current_combined:.3f} ➔ "
            f"Valor Canjeado: $1.000 | "
            f"Ganancia Neta: [bold green]+${net_profit:.2f} USDC (+{profit_pct:.2f}%)[/bold green] | "
            f"Balance Total: ${self.balance_usdc:.2f} USDC | "
            f"Mercado: {signal.market_question[:40]}..."
        )

    def evaluate_open_positions(self):
        """En arbitraje de paridad el canje es instantáneo (0 posiciones abiertas en riesgo)"""
        pass
