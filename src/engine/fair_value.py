import math
import time
from typing import Optional
from src.config import config
from src.utils.logger import get_logger

logger = get_logger("FairValueModel")

class FairValueModel:
    """
    Modelo matemático para estimar el precio teórico justo (Fair Value)
    de las acciones YES/NO de Polymarket ante movimientos rápidos de BTC.
    """
    
    @staticmethod
    def calculate_fair_probability(
        current_poly_mid: float,
        btc_price: float,
        btc_delta_5s: float,
        btc_velocity: float,
        is_bullish_market: bool = True
    ) -> float:
        """
        Calcula la probabilidad justa implícita.
        
        - current_poly_mid: Punto medio actual en Polymarket (entre best bid y best ask)
        - btc_delta_5s: Cambio de precio de BTC en los últimos 5 segundos en USD
        - btc_velocity: Velocidad del movimiento en USD/segundo
        - is_bullish_market: True si el contrato gana cuando BTC sube (YES = BTC Sube)
        """
        if current_poly_mid <= 0.0 or current_poly_mid >= 1.0:
            current_poly_mid = 0.50

        # Coeficiente de impacto: cuánto varía la probabilidad por cada $10 de movimiento rápido
        # Un movimiento de $100 en 5s representa un cambio significativo en probabilidades binarias a corto plazo
        sensitivity = 0.0015  # 0.15% de probabilidad por cada $1 de movimiento
        
        # Dirección del impacto según el tipo de contrato
        direction = 1.0 if is_bullish_market else -1.0
        
        # Ajuste de probabilidad por delta y velocidad (aceleración)
        prob_adjustment = (btc_delta_5s * sensitivity * direction) + (btc_velocity * 0.0005 * direction)
        
        # Limitar el salto máximo en una sola vela de detección a +/- 0.35 para evitar sobreajuste
        prob_adjustment = max(min(prob_adjustment, 0.35), -0.35)
        
        fair_value = current_poly_mid + prob_adjustment
        
        # Clampear entre 0.01 y 0.99 (límites de Polymarket)
        return max(0.01, min(0.99, round(fair_value, 4)))

    @staticmethod
    def is_market_bullish(question: str) -> bool:
        """
        Determina si el resultado YES del mercado está correlacionado positivamente con la subida de BTC.
        """
        q_lower = question.lower()
        # Palabras clave alcistas
        bullish_keywords = ["reach", "hit", "above", "up", "exceed", "higher", "ath", "surpass", ">", "at least"]
        # Palabras clave bajistas
        bearish_keywords = ["drop", "below", "down", "fall", "under", "crash", "<", "less than"]

        for b in bearish_keywords:
            if b in q_lower:
                return False
        return True
