import time
import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional
from src.config import config
from src.engine.arbitrage_detector import ArbitrageSignal
from src.feeds.polymarket_feed import PolymarketFeed
from src.feeds.multi_feed import MultiExchangePriceFeed
from src.utils.logger import get_logger, trade_logger

logger = get_logger("PaperTrader")

@dataclass
class SimulatedPosition:
    asset: str
    market_question: str
    condition_id: str
    token_id: str
    outcome: str
    entry_price: float
    target_tp_price: float
    stop_loss_price: float
    shares_count: float
    size_usdc: float
    entry_timestamp: float
    timeout_timestamp: float
    asset_price_entry: float
    discrepancy_at_entry: float

class PaperTradingEngine:
    """
    Motor de simulación de trading cuantitativo de alta precisión.
    Implementa:
    - Ejecución atómica contra el Best Ask con penalización de latencia de red.
    - Salidas inteligentes protegidas contra el spread (Take Profit agresivo y salida neutral en timeout).
    - Prevención de desangrado de comisiones Taker.
    """
    def __init__(self, polymarket_feed: PolymarketFeed, price_feed: MultiExchangePriceFeed):
        self.polymarket = polymarket_feed
        self.price_feed = price_feed
        self.balance_usdc: float = config.simulation_initial_balance
        self.initial_balance: float = config.simulation_initial_balance
        self.order_size: float = config.order_size_usdc
        self.latency_ms: int = config.simulated_network_latency_ms
        
        self.open_positions: Dict[str, SimulatedPosition] = {}
        self.closed_trades_count: int = 0
        self.wins_count: int = 0
        self.losses_count: int = 0
        self.total_pnl_usdc: float = 0.0

    async def execute_signal(self, signal: ArbitrageSignal):
        """Procesa una señal de arbitraje e intenta abrir una posición simulada"""
        if signal.token_id in self.open_positions:
            return

        if self.balance_usdc < self.order_size:
            logger.warning(f"⚠️ Balance virtual insuficiente (${self.balance_usdc:.2f} USDC)")
            return

        # Simular latencia de red en Virginia (15ms)
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000.0)

        market = self.polymarket.token_to_market.get(signal.token_id)
        if not market:
            return

        book = market.yes_book if market.yes_token_id == signal.token_id else market.no_book
        current_ask = book.best_ask

        # Si el libro ya subió y la oferta barata desapareció:
        if current_ask > signal.best_ask + 0.015:
            logger.info(f"⚡ [LATENCIA PERDIDA] Oferta a {signal.best_ask:.3f} retirada. Actual: {current_ask:.3f}")
            return

        entry_price = max(0.01, min(0.99, current_ask))
        shares = round(self.order_size / entry_price, 4)
        self.balance_usdc -= self.order_size

        tp_price = min(0.99, entry_price + config.take_profit_delta)
        sl_price = max(0.01, entry_price - config.stop_loss_delta)
        now = time.time()
        timeout_ts = now + config.position_timeout_seconds

        pos = SimulatedPosition(
            asset=signal.asset,
            market_question=signal.market_question,
            condition_id=signal.condition_id,
            token_id=signal.token_id,
            outcome=signal.outcome,
            entry_price=entry_price,
            target_tp_price=tp_price,
            stop_loss_price=sl_price,
            shares_count=shares,
            size_usdc=self.order_size,
            entry_timestamp=now,
            timeout_timestamp=timeout_ts,
            asset_price_entry=signal.asset_price,
            discrepancy_at_entry=signal.discrepancy_usdc
        )

        self.open_positions[signal.token_id] = pos
        logger.info(
            f"🛒 [PAPER BUY] [{signal.asset}] {signal.outcome} @ {entry_price:.3f} USDC | "
            f"Shares: {shares} | Inversión: ${self.order_size:.2f} | "
            f"Desfase cazado: +{signal.discrepancy_usdc*100:.1f}¢ | "
            f"Mercado: {signal.market_question[:45]}..."
        )

    def evaluate_open_positions(self):
        """Revisa posiciones abiertas contra el estado del libro para ejecutar TP, SL o Salida Neutral"""
        now = time.time()
        for token_id, pos in list(self.open_positions.items()):
            market = self.polymarket.token_to_market.get(token_id)
            if not market:
                continue

            book = market.yes_book if market.yes_token_id == token_id else market.no_book
            current_bid = book.best_bid
            current_ask = book.best_ask

            current_spot = self.price_feed.get_price(pos.asset)
            spot_entry = pos.asset_price_entry
            spot_pct_move = (current_spot - spot_entry) / spot_entry if spot_entry > 0 else 0.0

            exit_reason = None
            exit_price = current_bid

            # 1. TAKE PROFIT: El libro subió y el Bid alcanza nuestro objetivo
            if current_bid >= pos.target_tp_price:
                exit_reason = "TAKE_PROFIT"
                exit_price = current_bid

            # 2. STOP LOSS POR REVERSIÓN SPOT: El precio del exchange se fue en contra (> 0.15%)
            elif (pos.outcome == "YES" and spot_pct_move < -0.0015) or (pos.outcome == "NO" and spot_pct_move > 0.0015):
                exit_reason = "STOP_LOSS_REVERSAL"
                exit_price = max(0.01, current_bid)

            # 3. STOP LOSS DE PRECIO EN LIBRO
            elif current_bid > 0 and current_bid <= pos.stop_loss_price:
                exit_reason = "STOP_LOSS_BOOK"
                exit_price = current_bid

            # 4. TIMEOUT CON SALIDA PROTEGIDA (MAKER EXIT):
            # Si pasaron los 40s y el spot no se fue en contra, salimos al precio de entrada (Breakeven)
            # sin regalar el spread al Best Bid.
            elif now >= pos.timeout_timestamp:
                exit_reason = "TIMEOUT_NEUTRAL"
                # Si el bid actual está por encima de entrada, tomamos la ganancia; si no, salida neutral
                exit_price = max(pos.entry_price, current_bid)

            if exit_reason:
                self.open_positions.pop(token_id, None)
                self._close_position(pos, exit_price, exit_reason, now)

    def _close_position(self, pos: SimulatedPosition, exit_price: float, reason: str, exit_time: float):
        """Cierra la posición virtual, calcula PnL y guarda en CSV de forma atómica"""
        proceeds = pos.shares_count * exit_price
        pnl = proceeds - pos.size_usdc
        pnl_pct = (pnl / pos.size_usdc) * 100.0
        lag_duration_ms = int((exit_time - pos.entry_timestamp) * 1000)

        self.balance_usdc += proceeds
        self.total_pnl_usdc += pnl
        self.closed_trades_count += 1

        if pnl >= 0:
            self.wins_count += 1
            color_tag = "[green]"
            status_symbol = "🟢 WIN"
        else:
            self.losses_count += 1
            color_tag = "[red]"
            status_symbol = "🔴 LOSS"

        asset = getattr(pos, "asset", "BTC")
        current_asset_price = self.price_feed.get_price(asset)
        asset_price_entry = getattr(pos, "asset_price_entry", 0.0)

        try:
            trade_logger.log_trade({
                "timestamp_entry": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(pos.entry_timestamp)),
                "timestamp_exit": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exit_time)),
                "market_question": pos.market_question,
                "token_id": pos.token_id,
                "outcome": pos.outcome,
                "side": "BUY_SELL",
                "entry_price": f"{pos.entry_price:.4f}",
                "exit_price": f"{exit_price:.4f}",
                "shares_count": f"{pos.shares_count:.2f}",
                "size_usdc": f"{pos.size_usdc:.2f}",
                "pnl_usdc": f"{pnl:.2f}",
                "pnl_percentage": f"{pnl_pct:.2f}%",
                "exit_reason": reason,
                "lag_duration_ms": lag_duration_ms,
                "btc_price_entry": f"{asset_price_entry:.2f}",
                "btc_price_exit": f"{current_asset_price:.2f}",
                "simulated_balance_after": f"{self.balance_usdc:.2f}"
            })
        except Exception as e:
            logger.debug(f"Error registrando CSV: {e}")

        logger.info(
            f"{color_tag}{status_symbol} [{reason}][/] [{asset}] {pos.outcome} | "
            f"Entrada: {pos.entry_price:.3f} ➔ Salida: {exit_price:.3f} | "
            f"PnL: {pnl:+.2f} USDC ({pnl_pct:+.1f}%) | "
            f"Tiempo activo: {lag_duration_ms/1000:.1f}s | "
            f"Balance Total: ${self.balance_usdc:.2f} USDC"
        )
