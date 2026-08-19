import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from src.config import config
from src.feeds.multi_feed import MultiExchangePriceFeed
from src.feeds.polymarket_feed import PolymarketFeed, PolymarketMarket
from src.utils.logger import get_logger

logger = get_logger("ParityArbitrageDetector")

@dataclass
class ArbitrageSignal:
    asset: str
    market_question: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    yes_ask: float
    no_ask: float
    yes_ask_size: float
    no_ask_size: float
    combined_cost: float
    guaranteed_profit_per_pair: float
    profit_percentage: float
    available_pairs: float
    timestamp: float

class ArbitrageDetector:
    """
    Detector de Arbitraje Estructural Puro de Paridad Binaria (Negative Risk Parity).
    Supervisa todos los libros de órdenes en tiempo real de Polymarket y busca
    situaciones donde la suma del Best Ask de YES + NO sea estrictamente menor a 1.00 USDC.
    """
    def __init__(self, price_feed: MultiExchangePriceFeed, polymarket: PolymarketFeed):
        self.price_feed = price_feed
        self.polymarket = polymarket
        self.max_combined_ask = config.max_combined_ask_sum
        self.min_profit_pct = config.min_parity_profit_pct
        self.min_depth = config.min_share_depth
        self.last_signal_time: Dict[str, float] = {}

    def get_scan_diagnosis(self) -> Dict[str, Any]:
        """Genera un diagnóstico de paridad estructural para todos los mercados activos"""
        best_gap = -999.0
        best_candidate = "Ninguno"
        market_evals = []
        opportunities_count = 0

        for cond_id, market in self.polymarket.active_markets.items():
            yes_book = market.yes_book
            no_book = market.no_book

            # Verificar que ambos libros tengan precios válidos
            if yes_book.best_ask >= 0.999 or no_book.best_ask >= 0.999:
                continue
            if yes_book.best_ask <= 0.001 or no_book.best_ask <= 0.001:
                continue

            combined_cost = round(yes_book.best_ask + no_book.best_ask, 4)
            # Margen de beneficio garantizado (1.00 - Costo)
            guaranteed_margin = round(1.00 - combined_cost, 4)
            margin_pct = (guaranteed_margin / combined_cost) * 100.0 if combined_cost > 0 else 0.0

            is_opportunity = (combined_cost <= self.max_combined_ask) and (margin_pct >= self.min_profit_pct * 100.0)
            if is_opportunity:
                opportunities_count += 1

            if guaranteed_margin > best_gap:
                best_gap = guaranteed_margin
                best_candidate = f"[{market.asset}] {market.question[:28]}... (Margen: +{margin_pct:.2f}%)"

            market_evals.append({
                "asset": market.asset,
                "question": market.question,
                "yes_bid": yes_book.best_bid,
                "yes_ask": yes_book.best_ask,
                "no_bid": no_book.best_bid,
                "no_ask": no_book.best_ask,
                "combined_cost": combined_cost,
                "guaranteed_margin": guaranteed_margin,
                "margin_pct": margin_pct,
                "is_signal": is_opportunity
            })

        # Ordenar por el mejor margen de paridad (menor costo combinado)
        market_evals.sort(key=lambda x: x["combined_cost"])

        if opportunities_count > 0:
            verdict = f"⚡ ¡OPORTUNIDAD DE PARIDAD DETECTADA! Margen Libre de Riesgo de +{best_gap*100:.1f}¢ en {best_candidate}"
        else:
            verdict = f"🛡️ Vigilando Paridad Binaria (110+ Mercados) | Menor Costo Combinado (YES+NO): ${market_evals[0]['combined_cost']:.3f} si hubiere" if market_evals else "Sincronizando libros..."

        return {
            "consensus_prices": self.price_feed.consensus_prices,
            "max_diff": best_gap,
            "verdict": verdict,
            "market_evals": market_evals
        }

    def check_opportunities(self) -> List[ArbitrageSignal]:
        """Escanea todos los mercados y dispara señales de arbitraje de paridad 100% libres de riesgo"""
        signals: List[ArbitrageSignal] = []
        now = time.time()

        for cond_id, market in self.polymarket.active_markets.items():
            yes_book = market.yes_book
            no_book = market.no_book

            # Filtros de sanidad de libro
            if yes_book.best_ask >= 0.99 or no_book.best_ask >= 0.99:
                continue
            if yes_book.best_ask <= 0.01 or no_book.best_ask <= 0.01:
                continue

            combined_cost = yes_book.best_ask + no_book.best_ask
            guaranteed_profit = 1.00 - combined_cost

            # Condición de Oro: Costo YES + NO < MAX_COMBINED_ASK_SUM
            if combined_cost <= self.max_combined_ask:
                avail_yes = yes_book.best_ask_size
                avail_no = no_book.best_ask_size
                min_pairs = min(avail_yes, avail_no)

                if min_pairs >= self.min_depth:
                    # Enfriamiento por mercado de 5 segundos
                    if now - self.last_signal_time.get(cond_id, 0) > 5.0:
                        self.last_signal_time[cond_id] = now
                        profit_pct = (guaranteed_profit / combined_cost) * 100.0

                        signals.append(ArbitrageSignal(
                            asset=market.asset,
                            market_question=market.question,
                            condition_id=cond_id,
                            yes_token_id=market.yes_token_id,
                            no_token_id=market.no_token_id,
                            yes_ask=yes_book.best_ask,
                            no_ask=no_book.best_ask,
                            yes_ask_size=avail_yes,
                            no_ask_size=avail_no,
                            combined_cost=round(combined_cost, 4),
                            guaranteed_profit_per_pair=round(guaranteed_profit, 4),
                            profit_percentage=round(profit_pct, 2),
                            available_pairs=round(min_pairs, 2),
                            timestamp=now
                        ))

        return signals
