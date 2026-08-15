import asyncio
import json
import time
from collections import deque
from typing import Optional, Callable, Dict, Any
import websockets
from src.config import config
from src.utils.logger import get_logger

logger = get_logger("BinanceFeed")

class BinanceFeed:
    """
    Cliente WebSocket para capturar movimientos de BTC en Binance Futures y Spot a ultra-alta velocidad.
    """
    def __init__(self):
        self.spot_url = config.binance_spot_ws_url
        self.futures_url = config.binance_futures_ws_url
        self.current_price: float = 0.0
        self.futures_price: float = 0.0
        self.last_update_ts: float = 0.0
        
        # Historial de precios de los últimos 30 segundos (timestamp, precio)
        self.price_history: deque = deque(maxlen=600)
        self._running: bool = False
        self._on_tick_callbacks: list[Callable[[float, float], None]] = []

    def register_callback(self, callback: Callable[[float, float], None]):
        """Registra un callback que se llamará en cada tick (precio_actual, velocidad)"""
        self._on_tick_callbacks.append(callback)

    def get_price_delta(self, seconds_back: float = 5.0) -> float:
        """Calcula el cambio de precio en los últimos N segundos"""
        if not self.price_history or self.current_price == 0.0:
            return 0.0
        
        now = time.time()
        target_ts = now - seconds_back
        
        # Encontrar el precio más cercano al target_ts
        old_price = self.current_price
        for ts, price in self.price_history:
            if ts <= target_ts:
                old_price = price
                break
        
        return self.current_price - old_price

    def get_velocity(self) -> float:
        """Calcula la velocidad del movimiento en USD por segundo en la ventana configurada"""
        delta = self.get_price_delta(config.btc_momentum_window_seconds)
        if config.btc_momentum_window_seconds > 0:
            return delta / config.btc_momentum_window_seconds
        return 0.0

    async def start(self):
        self._running = True
        logger.info("Iniciando feeds WebSocket de Binance (Futures y Spot)...")
        # Iniciar Futures y Spot en paralelo
        await asyncio.gather(
            self._listen_futures(),
            self._listen_spot(),
            return_exceptions=True
        )

    async def stop(self):
        self._running = False
        logger.info("Deteniendo feeds de Binance...")

    async def _listen_futures(self):
        """Binance USD-M Futures (aggTrade) - Normalmente tiene el liderazgo de precio más rápido del mercado"""
        while self._running:
            try:
                async with websockets.connect(self.futures_url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("🟢 Conectado a Binance USD-M Futures WebSocket")
                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if "p" in data:
                            price = float(data["p"])
                            now = time.time()
                            self.futures_price = price
                            self.current_price = price  # Usamos futures como referencia primaria por velocidad
                            self.last_update_ts = now
                            self.price_history.appendleft((now, price))
                            
                            velocity = self.get_velocity()
                            for cb in self._on_tick_callbacks:
                                try:
                                    cb(price, velocity)
                                except Exception as cb_err:
                                    logger.error(f"Error en callback de tick: {cb_err}")
            except Exception as e:
                logger.warning(f"Reconectando Binance Futures en 2s: {e}")
                await asyncio.sleep(2.0)

    async def _listen_spot(self):
        """Binance Spot (btcusdt@trade) para confirmación de volumen spot"""
        while self._running:
            try:
                async with websockets.connect(self.spot_url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("🟢 Conectado a Binance Spot WebSocket")
                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if "p" in data:
                            spot_price = float(data["p"])
                            # Si futures estuviera inactivo, spot toma el relevo
                            if self.futures_price == 0:
                                self.current_price = spot_price
            except Exception as e:
                logger.warning(f"Reconectando Binance Spot en 3s: {e}")
                await asyncio.sleep(3.0)
