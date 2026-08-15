import math
import time
from typing import Optional
from src.config import config
from src.utils.logger import get_logger

logger = get_logger("FairValueModel")

class FairValueModel:
    """
    Modelo matemático universal para estimar el precio teórico justo (Fair Value)
    de las acciones YES/NO de Polymarket para cualquier activo (BTC, ETH, SOL, DOGE, XRP).
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
        Calcula la probabilidad justa implícita basándose en el cambio porcentual del activo.
        
        - current_poly_mid: Punto medio actual en Polymarket (entre best bid y best ask)
        - asset_price: Precio actual del activo en USD
        - pct_delta_5s: Variación porcentual en los últimos 5s (ej: +0.002 = +0.2%)
        - is_bullish_market: True si el contrato gana cuando el activo sube (YES = Sube)
        """
        if current_poly_mid <= 0.0 or current_poly_mid >= 1.0:
            current_poly_mid = 0.50

        # Multiplicador de sensibilidad porcentual:
        # Un movimiento del +0.2% (0.002) en spot genera un salto de ~+5% (0.05) en la probabilidad implícita
        sensitivity = 25.0
        
        direction = 1.0 if is_bullish_market else -1.0
        
        prob_adjustment = (pct_delta_5s * sensitivity * direction)
        
        # Limitar el salto máximo por vela a +/- 0.35 para evitar sobreajuste
        prob_adjustment = max(min(prob_adjustment, 0.35), -0.35)
        
        fair_value = current_poly_mid + prob_adjustment
        
        return max(0.01, min(0.99, round(fair_value, 4)))

    @staticmethod
    def is_market_bullish(question: str) -> bool:
        """
        Determina si el resultado YES del mercado está correlacionado positivamente con la subida del activo.
        """
        q_lower = question.lower()
        bullish_keywords = ["reach", "hit", "above", "up", "exceed", "higher", "ath", "surpass", ">", "at least", "gain"]
        bearish_keywords = ["drop", "below", "down", "fall", "under", "crash", "<", "less than", "lose"]

        for b in bearish_keywords:
            if b in q_lower:
                return False
        return True
