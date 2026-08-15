import time
from dataclasses import dataclass
from typing import Optional, List
from src.config import config
from src.feeds.binance_feed import BinanceFeed
from src.feeds.coinbase_feed import CoinbaseFeed
from src.feeds.polymarket_feed import PolymarketFeed, PolymarketMarket
from src.engine.fair_value import FairValueModel
from src.utils.logger import get_logger

logger = get_logger("ArbitrageDetector")

@dataclass
class ArbitrageSignal:
    market_question: str
    condition_id: str
    token_id: str
    outcome: str  # "YES" o "NO"
    side: str     # "BUY"
    best_ask: float
    best_bid: float
    fair_value: float
    discrepancy_usdc: float
    available_liquidity_usdc: float
    btc_price: float
    btc_delta_5s: float
    btc_velocity: float
    timestamp: float

class ArbitrageDetector:
    """
    Analiza en tiempo real los feeds de Binance/Coinbase y los libros de Polymarket para encontrar desfases.
    """
    def __init__(self, binance: BinanceFeed, coinbase: CoinbaseFeed, polymarket: PolymarketFeed):
        self.binance = binance
        self.coinbase = coinbase
        self.polymarket = polymarket
        self.min_discrepancy = config.min_price_discrepancy
        self.fast_move_threshold = config.btc_fast_move_threshold_usd
        self.last_signal_time: dict[str, float] = {}  # Throttle por token

    def check_opportunities(self) -> List[ArbitrageSignal]:
        """Evalúa todos los mercados activos y genera señales si detecta un retraso explotable"""
        signals: List[ArbitrageSignal] = []
        btc_price = self.binance.current_price
        
        if btc_price == 0:
            return signals

        btc_delta = self.binance.get_price_delta(config.btc_momentum_window_seconds)
        btc_velocity = self.binance.get_velocity()
        now = time.time()

        for cond_id, market in self.polymarket.active_markets.items():
            is_bullish = FairValueModel.is_market_bullish(market.question)
            
            # --- EVALUAR TOKEN YES ---
            yes_book = market.yes_book
            if yes_book.best_ask < 0.99 and yes_book.best_ask > 0.01:
                mid_yes = (yes_book.best_bid + yes_book.best_ask) / 2.0 if yes_book.best_bid > 0 else yes_book.best_ask
                fair_yes = FairValueModel.calculate_fair_probability(
                    current_poly_mid=mid_yes,
                    btc_price=btc_price,
                    btc_delta_5s=btc_delta,
                    btc_velocity=btc_velocity,
                    is_bullish_market=is_bullish
                )

                # Si el valor justo es significativamente superior a la mejor oferta de venta en Polymarket
                # Significa que alguien dejó una orden de venta barata que aún no ha actualizado al alza
                discrepancy_yes = fair_yes - yes_book.best_ask
                if discrepancy_yes >= self.min_discrepancy and abs(btc_delta) >= self.fast_move_threshold:
                    # Throttle: evitar spamear la misma señal más de 1 vez cada 5 segundos
                    if now - self.last_signal_time.get(market.yes_token_id, 0) > 5.0:
                        self.last_signal_time[market.yes_token_id] = now
                        liquidity = yes_book.best_ask_size * yes_book.best_ask
                        signals.append(ArbitrageSignal(
                            market_question=market.question,
                            condition_id=market.condition_id,
                            token_id=market.yes_token_id,
                            outcome="YES",
                            side="BUY",
                            best_ask=yes_book.best_ask,
                            best_bid=yes_book.best_bid,
                            fair_value=fair_yes,
                            discrepancy_usdc=round(discrepancy_yes, 4),
                            available_liquidity_usdc=round(liquidity, 2),
                            btc_price=btc_price,
                            btc_delta_5s=btc_delta,
                            btc_velocity=btc_velocity,
                            timestamp=now
                        ))

            # --- EVALUAR TOKEN NO ---
            no_book = market.no_book
            if no_book.best_ask < 0.99 and no_book.best_ask > 0.01:
                mid_no = (no_book.best_bid + no_book.best_ask) / 2.0 if no_book.best_bid > 0 else no_book.best_ask
                # El valor de NO es el inverso del valor de YES
                fair_no = FairValueModel.calculate_fair_probability(
                    current_poly_mid=mid_no,
                    btc_price=btc_price,
                    btc_delta_5s=btc_delta,
                    btc_velocity=btc_velocity,
                    is_bullish_market=not is_bullish  # Invierte dirección
                )

                discrepancy_no = fair_no - no_book.best_ask
                if discrepancy_no >= self.min_discrepancy and abs(btc_delta) >= self.fast_move_threshold:
                    if now - self.last_signal_time.get(market.no_token_id, 0) > 5.0:
                        self.last_signal_time[market.no_token_id] = now
                        liquidity = no_book.best_ask_size * no_book.best_ask
                        signals.append(ArbitrageSignal(
                            market_question=market.question,
                            condition_id=market.condition_id,
                            token_id=market.no_token_id,
                            outcome="NO",
                            side="BUY",
                            best_ask=no_book.best_ask,
                            best_bid=no_book.best_bid,
                            fair_value=fair_no,
                            discrepancy_usdc=round(discrepancy_no, 4),
                            available_liquidity_usdc=round(liquidity, 2),
                            btc_price=btc_price,
                            btc_delta_5s=btc_delta,
                            btc_velocity=btc_velocity,
                            timestamp=now
                        ))

        return signals
