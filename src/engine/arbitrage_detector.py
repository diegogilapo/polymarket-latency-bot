import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from src.config import config
from src.feeds.multi_feed import MultiExchangePriceFeed
from src.feeds.polymarket_feed import PolymarketFeed, PolymarketMarket
from src.engine.fair_value import FairValueModel
from src.utils.logger import get_logger

logger = get_logger("MarketMakerDetector")

@dataclass
class MarketMakingOpportunity:
    asset: str
    market_question: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    fair_price: float
    limit_bid: float
    limit_ask: float
    market_best_bid: float
    market_best_ask: float
    spread_captured: float
    mispricing_type: Optional[str]  # "CHEAP_ASK", "EXPENSIVE_BID", "SPREAD_QUOTING"
    mispricing_edge: float
    timestamp: float

class ArbitrageDetector:
    """
    Motor Cuantitativo de Detección de Precios Erróneos y Cotización Límite (Maker).
    Evalúa 110+ mercados de Polymarket y calcula las órdenes límite óptimas (Bid y Ask)
    para capturar el spread y explotar precios descalibrados de usuarios retail.
    """
    def __init__(self, price_feed: MultiExchangePriceFeed, polymarket: PolymarketFeed):
        self.price_feed = price_feed
        self.polymarket = polymarket
        self.target_spread = config.target_spread_cents
        self.inventory_tracker: Dict[str, float] = {}

    def get_scan_diagnosis(self) -> Dict[str, Any]:
        """Genera un diagnóstico completo de precios teóricos, órdenes límite y descalibraciones"""
        market_evals = []
        best_edge = 0.0
        best_candidate = "Ninguno"
        active_mispricings = 0

        for cond_id, market in self.polymarket.active_markets.items():
            asset = market.asset
            asset_price = self.price_feed.get_price(asset)
            if asset_price <= 0:
                continue

            pct_delta = self.price_feed.get_pct_delta(asset, config.momentum_window_seconds)
            vel = self.price_feed.get_velocity(asset)

            yes_book = market.yes_book
            if yes_book.best_ask >= 0.98 or yes_book.best_ask <= 0.02:
                continue

            # Precio medio actual del libro de Polymarket
            mid_poly = (yes_book.best_bid + yes_book.best_ask) / 2.0 if yes_book.best_bid > 0 else yes_book.best_ask
            is_bullish = FairValueModel.is_market_bullish(market.question)

            # 1. Calcular Valor Justo Real
            fair_price = FairValueModel.calculate_fair_mid(
                current_poly_mid=mid_poly,
                asset_price=asset_price,
                pct_delta_3s=pct_delta,
                asset_velocity=vel,
                is_bullish_market=is_bullish
            )

            # 2. Calcular Órdenes Límite Óptimas (Bid / Ask) según inventario
            current_inv = self.inventory_tracker.get(cond_id, 0.0)
            our_bid, our_ask = FairValueModel.calculate_optimal_quotes(
                fair_price=fair_price,
                inventory_shares=current_inv,
                target_spread=self.target_spread,
                skew_factor=config.inventory_skew_factor
            )

            # 3. Detectar Precios Erróneos en el Mercado
            mispricing_type = "SPREAD_QUOTING"
            edge = round(our_ask - our_bid, 3)

            # Caso A: El mercado vende demasiado barato (Ask del mercado < Nuestro Valor Justo)
            if yes_book.best_ask < our_bid:
                mispricing_type = "CHEAP_ASK"
                edge = round(our_bid - yes_book.best_ask + 0.020, 3)
                active_mispricings += 1

            # Caso B: El mercado compra demasiado caro (Bid del mercado > Nuestro Valor Justo)
            elif yes_book.best_bid > our_ask:
                mispricing_type = "EXPENSIVE_BID"
                edge = round(yes_book.best_bid - our_ask + 0.020, 3)
                active_mispricings += 1

            if edge > best_edge:
                best_edge = edge
                best_candidate = f"[{asset}] {market.question[:28]}... ({mispricing_type} +{edge*100:.1f}¢)"

            market_evals.append({
                "asset": asset,
                "question": market.question,
                "condition_id": cond_id,
                "fair_price": fair_price,
                "our_bid": our_bid,
                "our_ask": our_ask,
                "market_bid": yes_book.best_bid,
                "market_ask": yes_book.best_ask,
                "spread_captured": round(our_ask - our_bid, 3),
                "mispricing_type": mispricing_type,
                "edge": edge,
                "inventory": current_inv,
                "is_signal": (mispricing_type in ("CHEAP_ASK", "EXPENSIVE_BID")) or (edge >= config.min_spread_cents)
            })

        # Ordenar por mayor ventaja estadística
        market_evals.sort(key=lambda x: -x["edge"])

        if active_mispricings > 0:
            verdict = f"🎯 PRECIO ERRÓNEO DETECTADO: Capturando +{best_edge*100:.1f}¢ en {best_candidate}"
        else:
            verdict = f"🟢 Cotizando Órdenes Límite Bid/Ask | Captura Media de Spread: +{self.target_spread*100:.1f}¢ por ciclo"

        return {
            "consensus_prices": self.price_feed.consensus_prices,
            "max_diff": best_edge,
            "verdict": verdict,
            "market_evals": market_evals
        }

    def check_opportunities(self) -> List[MarketMakingOpportunity]:
        """Genera órdenes de cotización y ejecución de arbitraje de precios erróneos"""
        opportunities: List[MarketMakingOpportunity] = []
        now = time.time()

        for cond_id, market in self.polymarket.active_markets.items():
            yes_book = market.yes_book
            if yes_book.best_ask >= 0.98 or yes_book.best_ask <= 0.02:
                continue

            asset = market.asset
            asset_price = self.price_feed.get_price(asset)
            if asset_price <= 0:
                continue

            pct_delta = self.price_feed.get_pct_delta(asset, config.momentum_window_seconds)
            vel = self.price_feed.get_velocity(asset)

            mid_poly = (yes_book.best_bid + yes_book.best_ask) / 2.0 if yes_book.best_bid > 0 else yes_book.best_ask
            is_bullish = FairValueModel.is_market_bullish(market.question)

            fair_price = FairValueModel.calculate_fair_mid(
                current_poly_mid=mid_poly,
                asset_price=asset_price,
                pct_delta_3s=pct_delta,
                asset_velocity=vel,
                is_bullish_market=is_bullish
            )

            current_inv = self.inventory_tracker.get(cond_id, 0.0)
            our_bid, our_ask = FairValueModel.calculate_optimal_quotes(
                fair_price=fair_price,
                inventory_shares=current_inv,
                target_spread=self.target_spread,
                skew_factor=config.inventory_skew_factor
            )

            mispricing_type = "SPREAD_QUOTING"
            edge = round(our_ask - our_bid, 3)

            if yes_book.best_ask < our_bid:
                mispricing_type = "CHEAP_ASK"
                edge = round(our_bid - yes_book.best_ask + 0.020, 3)
            elif yes_book.best_bid > our_ask:
                mispricing_type = "EXPENSIVE_BID"
                edge = round(yes_book.best_bid - our_ask + 0.020, 3)

            opportunities.append(MarketMakingOpportunity(
                asset=asset,
                market_question=market.question,
                condition_id=cond_id,
                yes_token_id=market.yes_token_id,
                no_token_id=market.no_token_id,
                fair_price=fair_price,
                limit_bid=our_bid,
                limit_ask=our_ask,
                market_best_bid=yes_book.best_bid,
                market_best_ask=yes_book.best_ask,
                spread_captured=round(our_ask - our_bid, 3),
                mispricing_type=mispricing_type,
                mispricing_edge=edge,
                timestamp=now
            ))

        return opportunities
