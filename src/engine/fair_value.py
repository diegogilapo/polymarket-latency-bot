import math
from typing import Optional
from src.config import config
from src.utils.logger import get_logger

logger = get_logger("FairValueModel")

class FairValueModel:
    """
    Modelo matemático de valoración de probabilidades justas y pricing de opciones binarias.
    Calcula el precio de equilibrio teórico para anclar las órdenes límite de compra y venta.
    """

    @staticmethod
    def calculate_fair_mid(
        current_poly_mid: float,
        asset_price: float,
        pct_delta_3s: float,
        asset_velocity: float,
        is_bullish_market: bool = True
    ) -> float:
        """
        Calcula el precio medio de equilibrio teórico (Fair Value)
        anclado en la microestructura de Polymarket y los precios de los exchanges spot.
        """
        if current_poly_mid <= 0.001:
            return 0.001
        if current_poly_mid >= 0.999:
            return 0.999

        direction = 1.0 if is_bullish_market else -1.0
        
        # Ponderación Gamma de opción binaria (máxima en P=0.50)
        gamma = 4.0 * current_poly_mid * (1.0 - current_poly_mid)
        
        # Desplazamiento proporcional suave (evita sobreajustes)
        prob_shift = pct_delta_3s * 15.0 * gamma * direction
        prob_shift = max(min(prob_shift, 0.08), -0.08)
        
        fair_price = current_poly_mid + prob_shift
        return round(max(0.01, min(0.99, fair_price)), 3)

    @staticmethod
    def calculate_optimal_quotes(
        fair_price: float,
        inventory_shares: float,
        target_spread: float = 0.030,
        skew_factor: float = 0.00008
    ) -> tuple[float, float]:
        """
        Modelo Avellaneda-Stoikov:
        Ajusta el precio límite de compra (Bid) y venta (Ask) según el inventario acumulado.
        - Si tenemos exceso de inventario (long), bajamos los precios para desprendernos de acciones.
        - Si estamos cortos (short), subimos los precios para recomprar.
        """
        half_spread = max(0.008, target_spread / 2.0)
        
        # Ajuste por inventario
        inventory_skew = inventory_shares * skew_factor
        
        optimal_bid = round(max(0.01, fair_price - half_spread - inventory_skew), 3)
        optimal_ask = round(min(0.99, fair_price + half_spread - inventory_skew), 3)
        
        # Asegurar que Ask sea siempre mayor que Bid al menos por 1 centavo
        if optimal_ask <= optimal_bid:
            optimal_ask = round(optimal_bid + 0.015, 3)

        return optimal_bid, optimal_ask

    @staticmethod
    def is_market_bullish(question: str) -> bool:
        q_lower = question.lower()
        bullish_keywords = ["up", "reach", "hit", "above", "exceed", "higher", "ath", "surpass", ">", "at least", "gain", "win"]
        bearish_keywords = ["down", "drop", "below", "fall", "under", "crash", "<", "less than", "lose", "dip"]

        for b in bearish_keywords:
            if b in q_lower:
                return False
        return True
