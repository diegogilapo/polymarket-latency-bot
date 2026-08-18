import math
import time
from typing import Optional
from src.config import config
from src.utils.logger import get_logger

logger = get_logger("FairValueModel")

class FairValueModel:
    """
    Modelo matemático cuantitativo para estimar el precio teórico justo (Fair Value)
    de las acciones YES/NO de Polymarket en la Zona Activa de Probabilidad.
    """

    @staticmethod
    def calculate_fair_probability(
        current_poly_mid: float,
        asset_price: float,
        pct_delta_5s: float,
        asset_velocity: float,
        is_bullish_market: bool = True
    ) -> float:
        """
        Calcula el valor justo implícito en tiempo real.
        - En contratos At-The-Money / 50-50 (P ~ 0.50), la sensibilidad Gamma es máxima.
        - Un movimiento spot del +0.05% a +0.10% genera un desplazamiento de +2.5¢ a +5.0¢.
        - NO clampa a mínimos artificiales para evitar desfases falsos en libros ilíquidos.
        """
        if current_poly_mid <= 0.0001:
            return 0.0001
        if current_poly_mid >= 0.9999:
            return 0.9999

        direction = 1.0 if is_bullish_market else -1.0
        
        # Ponderación Gamma de opción binaria: máxima en P = 0.50 (4 * 0.5 * 0.5 = 1.0)
        gamma_factor = 4.0 * current_poly_mid * (1.0 - current_poly_mid)
        
        # Sensibilidad proporcional al impulso spot en 5s
        # 0.001 (0.10% spot) * 40.0 * 1.0 = +0.040 (+4.0 centavos de variación)
        prob_shift = pct_delta_5s * 40.0 * gamma_factor * direction
        
        # Limitar desplazamiento máximo por vela para evitar sobreajuste
        prob_shift = max(min(prob_shift, 0.20), -0.20)
        
        fair_value = current_poly_mid + prob_shift
        return round(max(0.001, min(0.999, fair_value)), 4)

    @staticmethod
    def is_market_bullish(question: str) -> bool:
        q_lower = question.lower()
        bullish_keywords = ["up", "reach", "hit", "above", "exceed", "higher", "ath", "surpass", ">", "at least", "gain", "win"]
        bearish_keywords = ["down", "drop", "below", "fall", "under", "crash", "<", "less than", "lose", "dip"]

        for b in bearish_keywords:
            if b in q_lower:
                return False
        return True
