import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from src.config import config
from src.feeds.multi_feed import MultiExchangePriceFeed
from src.feeds.polymarket_feed import PolymarketFeed, PolymarketMarket
from src.engine.fair_value import FairValueModel
from src.utils.logger import get_logger

logger = get_logger("ArbitrageDetector")

@dataclass
class ArbitrageSignal:
    asset: str
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
    asset_price: float
    pct_delta_5s: float
    timestamp: float

class ArbitrageDetector:
    """
    Analiza en tiempo real los feeds multi-exchange y los libros de Polymarket
    para cualquier activo soportado (BTC, ETH, SOL, DOGE, XRP).
    """
    def __init__(self, price_feed: MultiExchangePriceFeed, polymarket: PolymarketFeed):
        self.price_feed = price_feed
        self.polymarket = polymarket
        self.min_discrepancy = config.min_price_discrepancy
        self.fast_move_pct_threshold = config.fast_move_pct_threshold
        self.last_signal_time: dict[str, float] = {}

    def get_scan_diagnosis(self) -> Dict[str, Any]:
        """Genera un diagnóstico detallado y transparente para todos los activos"""
        max_diff = 0.0
        best_candidate = "Ninguno"
        market_evals = []
        any_momentum = False

        for cond_id, market in self.polymarket.active_markets.items():
            asset = market.asset
            asset_price = self.price_feed.get_price(asset)
            if asset_price <= 0:
                continue

            pct_delta = self.price_feed.get_pct_delta(asset, config.momentum_window_seconds)
            vel = self.price_feed.get_velocity(asset)
            has_momentum = abs(pct_delta) >= self.fast_move_pct_threshold
            if has_momentum:
                any_momentum = True

            is_bullish = FairValueModel.is_market_bullish(market.question)
            
            # Evaluar YES
            yes_book = market.yes_book
            mid_yes = (yes_book.best_bid + yes_book.best_ask) / 2.0 if yes_book.best_bid > 0 else yes_book.best_ask
            fair_yes = FairValueModel.calculate_fair_probability(
                current_poly_mid=mid_yes,
                asset_price=asset_price,
                pct_delta_5s=pct_delta,
                asset_velocity=vel,
                is_bullish_market=is_bullish
            )
            diff_yes = fair_yes - yes_book.best_ask

            # Evaluar NO
            no_book = market.no_book
            mid_no = (no_book.best_bid + no_book.best_ask) / 2.0 if no_book.best_bid > 0 else no_book.best_ask
            fair_no = FairValueModel.calculate_fair_probability(
                current_poly_mid=mid_no,
                asset_price=asset_price,
                pct_delta_5s=pct_delta,
                asset_velocity=vel,
                is_bullish_market=not is_bullish
            )
            diff_no = fair_no - no_book.best_ask

            top_diff = max(diff_yes, diff_no)
            outcome = "YES" if diff_yes >= diff_no else "NO"
            best_ask = yes_book.best_ask if outcome == "YES" else no_book.best_ask
            best_bid = yes_book.best_bid if outcome == "YES" else no_book.best_bid
            fair_val = fair_yes if outcome == "YES" else fair_no

            if top_diff > max_diff:
                max_diff = top_diff
                best_candidate = f"[{asset}] {market.question[:28]}... ({outcome})"

            market_evals.append({
                "asset": asset,
                "question": market.question,
                "outcome": outcome,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "fair_value": fair_val,
                "diff": top_diff,
                "asset_price": asset_price,
                "pct_delta": pct_delta,
                "is_signal": top_diff >= self.min_discrepancy and has_momentum
            })

        btc_p = self.price_feed.get_price("BTC")
        btc_pct = self.price_feed.get_pct_delta("BTC", config.momentum_window_seconds)

        verdict = "⏳ ESPERANDO IMPULSO EN CRIPTO"
        if not any_momentum:
            verdict = f"⏸️ Sin señal: Impulsos spot < {self.fast_move_pct_threshold*100:.2f}% | Mayor desfase en libros: +{max_diff*100:.1f}¢"
        elif max_diff < self.min_discrepancy:
            verdict = f"⏸️ Sin señal: Mayor desfase (+{max_diff*100:.1f}¢) < Umbral mínimo (+{self.min_discrepancy*100:.1f}¢)"
        else:
            verdict = f"⚡ ¡SEÑAL DETECTADA! Desfase cazable de +{max_diff*100:.1f}¢ en {best_candidate}"

        return {
            "btc_price": btc_p,
            "btc_pct_delta": btc_pct,
            "consensus_prices": self.price_feed.consensus_prices,
            "max_diff": max_diff,
            "verdict": verdict,
            "market_evals": market_evals
        }

    def check_opportunities(self) -> List[ArbitrageSignal]:
        """Evalúa todos los mercados activos multi-cripto y genera señales ante desfases"""
        signals: List[ArbitrageSignal] = []
        now = time.time()

        for cond_id, market in self.polymarket.active_markets.items():
            asset = market.asset
            asset_price = self.price_feed.get_price(asset)
            if asset_price <= 0:
                continue

            pct_delta = self.price_feed.get_pct_delta(asset, config.momentum_window_seconds)
            vel = self.price_feed.get_velocity(asset)
            has_momentum = abs(pct_delta) >= self.fast_move_pct_threshold

            is_bullish = FairValueModel.is_market_bullish(market.question)
            
            # --- EVALUAR TOKEN YES ---
            yes_book = market.yes_book
            if yes_book.best_ask < 0.99 and yes_book.best_ask > 0.01:
                mid_yes = (yes_book.best_bid + yes_book.best_ask) / 2.0 if yes_book.best_bid > 0 else yes_book.best_ask
                fair_yes = FairValueModel.calculate_fair_probability(
                    current_poly_mid=mid_yes,
                    asset_price=asset_price,
                    pct_delta_5s=pct_delta,
                    asset_velocity=vel,
                    is_bullish_market=is_bullish
                )

                discrepancy_yes = fair_yes - yes_book.best_ask
                if discrepancy_yes >= self.min_discrepancy and has_momentum:
                    if now - self.last_signal_time.get(market.yes_token_id, 0) > 5.0:
                        self.last_signal_time[market.yes_token_id] = now
                        liquidity = yes_book.best_ask_size * yes_book.best_ask
                        signals.append(ArbitrageSignal(
                            asset=asset,
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
                            asset_price=asset_price,
                            pct_delta_5s=pct_delta,
                            timestamp=now
                        ))

            # --- EVALUAR TOKEN NO ---
            no_book = market.no_book
            if no_book.best_ask < 0.99 and no_book.best_ask > 0.01:
                mid_no = (no_book.best_bid + no_book.best_ask) / 2.0 if no_book.best_bid > 0 else no_book.best_ask
                fair_no = FairValueModel.calculate_fair_probability(
                    current_poly_mid=mid_no,
                    asset_price=asset_price,
                    pct_delta_5s=pct_delta,
                    asset_velocity=vel,
                    is_bullish_market=not is_bullish
                )

                discrepancy_no = fair_no - no_book.best_ask
                if discrepancy_no >= self.min_discrepancy and has_momentum:
                    if now - self.last_signal_time.get(market.no_token_id, 0) > 5.0:
                        self.last_signal_time[market.no_token_id] = now
                        liquidity = no_book.best_ask_size * no_book.best_ask
                        signals.append(ArbitrageSignal(
                            asset=asset,
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
                            asset_price=asset_price,
                            pct_delta_5s=pct_delta,
                            timestamp=now
                        ))

        return signals
