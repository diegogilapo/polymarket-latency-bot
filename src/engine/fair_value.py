import math
import time
from typing import Optional
from src.config import config
from src.utils.logger import get_logger

logger = get_logger("FairValueModel")

class FairValueModel:
    """
    Modelo matemático cuantitativo para calcular el Fair Value (probabilidad justa)
    de contratos binarios de Polymarket ante movimientos rápidos en los feeds spot.
    """
    
    @staticmethod
    def norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def calculate_fair_probability(
        current_poly_mid: float,
        asset_price: float,
        pct_delta_5s: float,
        asset_velocity: float,
        is_bullish_market: bool = True,
        time_to_expiry_hours: float = 24.0
    ) -> float:
        """
        Calcula la probabilidad justa implícita considerando:
        1. Delta de opción binaria (sensibilidad no lineal).
        2. Magnitud y velocidad del impulso en los exchanges.
        3. Dirección correlacionada del contrato (Bullish YES / Bearish NO).
        """
        if current_poly_mid <= 0.001 or current_poly_mid >= 0.999:
            current_poly_mid = 0.50

        direction = 1.0 if is_bullish_market else -1.0
        
        # Sensibilidad adaptativa: Mayor cuando el precio de Polymarket está en la zona activa (0.20 - 0.80)
        # La derivada dN(d2)/dS es máxima cuando el contrato está At-The-Money (P ~ 0.50)
        gamma_weight = 4.0 * current_poly_mid * (1.0 - current_poly_mid)  # Máximo = 1.0 en 0.50
        
        # Coeficiente de respuesta: un movimiento de +0.10% spot genera un salto de ~+4¢ a +6¢ en P(YES)
        multiplier = 45.0 * gamma_weight
        
        prob_adjustment = (pct_delta_5s * multiplier * direction)
        
        # Limitar ajuste máximo por impulso individual a +/- 0.25 para evitar sobre-reacción
        prob_adjustment = max(min(prob_adjustment, 0.25), -0.25)
        
        fair_value = current_poly_mid + prob_adjustment
        return max(0.01, min(0.99, round(fair_value, 4)))

    @staticmethod
    def is_market_bullish(question: str) -> bool:
        q_lower = question.lower()
        bullish_keywords = ["reach", "hit", "above", "up", "exceed", "higher", "ath", "surpass", ">", "at least", "gain", "win"]
        bearish_keywords = ["drop", "below", "down", "fall", "under", "crash", "<", "less than", "lose"]

        for b in bearish_keywords:
            if b in q_lower:
                return False
        return True
