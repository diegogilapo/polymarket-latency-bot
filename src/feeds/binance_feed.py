import asyncio
import json
import time
from collections import deque
from typing import Optional, Callable, Dict, Any
import websockets
from src.config import config
from src.utils.logger import get_logger

logger = get_logger("PriceFeed")

class BinanceFeed:
    """
    Cliente WebSocket multi-exchange ultra-rápido:
    - Intenta Binance Global Futures & Spot
    - Si detecta Geo-bloqueo en EE.UU. (HTTP 451 en Render/AWS US East), conmuta automáticamente a Binance.US y Kraken
    - Mantiene el historial de precios y cálculo de impulso/velocidad en milisegundos
    """
    def __init__(self):
        self.spot_url = config.binance_spot_ws_url
        self.futures_url = config.binance_futures_ws_url
        self.binance_us_url = "wss://stream.binance.us:9443/ws/btcusdt@trade"
        self.kraken_url = "wss://ws.kraken.com"
        
        self.current_price: float = 0.0
        self.futures_price: float = 0.0
        self.last_update_ts: float = 0.0
        self.active_source: str = "Iniciando..."
        
        self._is_us_geoblocked: bool = False
        self.price_history: deque = deque(maxlen=600)
        self._running: bool = False
        self._on_tick_callbacks: list[Callable[[float, float], None]] = []

    def register_callback(self, callback: Callable[[float, float], None]):
        """Registra un callback que se llamará en cada tick (precio_actual, velocidad)"""
        self._on_tick_callbacks.append(callback)

    def record_tick(self, price: float, source: str):
        """Registra un tick de cualquier feed activo (Binance, Binance.US, Coinbase, Kraken)"""
        if price <= 0.0:
            return
        now = time.time()
        self.current_price = price
        self.active_source = source
        self.last_update_ts = now
        self.price_history.appendleft((now, price))
        
        velocity = self.get_velocity()
        for cb in self._on_tick_callbacks:
            try:
                cb(price, velocity)
            except Exception as cb_err:
                logger.debug(f"Error en callback de tick: {cb_err}")

    def get_price_delta(self, seconds_back: float = 5.0) -> float:
        """Calcula el cambio de precio en los últimos N segundos"""
        if not self.price_history or self.current_price == 0.0:
            return 0.0
        
        now = time.time()
        target_ts = now - seconds_back
        
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
        logger.info("Iniciando feeds de precio en tiempo real (Binance / US Feeds)...")
        await asyncio.gather(
            self._listen_futures_global(),
            self._listen_spot_global(),
            self._listen_kraken(),
            return_exceptions=True
        )

    async def stop(self):
        self._running = False
        logger.info("Deteniendo feeds de precio...")

    async def _listen_futures_global(self):
        """Binance USD-M Futures Global (si no está en EE.UU.)"""
        while self._running:
            if self._is_us_geoblocked:
                # Si está en EE.UU., usar Binance.US en su lugar
                await self._listen_binance_us()
                break

            try:
                async with websockets.connect(self.futures_url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("🟢 Conectado a Binance USD-M Futures Global WebSocket")
                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if "p" in data:
                            price = float(data["p"])
                            self.futures_price = price
                            self.record_tick(price, "Binance Futures")
            except Exception as e:
                err_str = str(e)
                if "451" in err_str or "Unavailable For Legal Reasons" in err_str:
                    if not self._is_us_geoblocked:
                        self._is_us_geoblocked = True
                        logger.info("ℹ️ Servidor en EE.UU. detectado (Binance Global restringido). Conmutando automáticamente a Binance.US + Coinbase + Kraken.")
                    await asyncio.sleep(1.0)
                else:
                    logger.warning(f"Reconectando Binance Futures en 3s: {e}")
                    await asyncio.sleep(3.0)

    async def _listen_spot_global(self):
        """Binance Spot Global"""
        while self._running:
            if self._is_us_geoblocked:
                # Si estamos en EE.UU., no intentar Binance Spot global para evitar spam de 451
                await asyncio.sleep(10.0)
                continue

            try:
                async with websockets.connect(self.spot_url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("🟢 Conectado a Binance Spot Global WebSocket")
                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if "p" in data:
                            self.record_tick(float(data["p"]), "Binance Spot")
            except Exception as e:
                err_str = str(e)
                if "451" in err_str:
                    self._is_us_geoblocked = True
                    await asyncio.sleep(5.0)
                else:
                    await asyncio.sleep(3.0)

    async def _listen_binance_us(self):
        """Binance.US Spot para servidores en EE.UU."""
        while self._running:
            try:
                async with websockets.connect(self.binance_us_url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("🟢 Conectado a Binance.US Spot WebSocket")
                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if "p" in data:
                            self.record_tick(float(data["p"]), "Binance.US")
            except Exception as e:
                logger.debug(f"Reconectando Binance.US en 3s: {e}")
                await asyncio.sleep(3.0)

    async def _listen_kraken(self):
        """Kraken WebSocket para ultra-baja latencia en EE.UU. y redundancia constante"""
        while self._running:
            try:
                async with websockets.connect(self.kraken_url, ping_interval=20, ping_timeout=10) as ws:
                    sub = {
                        "event": "subscribe",
                        "pair": ["XBT/USD"],
                        "subscription": {"name": "ticker"}
                    }
                    await ws.send(json.dumps(sub))
                    logger.info("🟢 Conectado a Kraken WebSocket (XBT/USD)")

                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if isinstance(data, list) and len(data) > 1:
                            ticker_data = data[1]
                            if isinstance(ticker_data, dict) and "c" in ticker_data:
                                # "c" es [price, lot_volume]
                                last_price = float(ticker_data["c"][0])
                                self.record_tick(last_price, "Kraken")
            except Exception as e:
                logger.debug(f"Reconectando Kraken en 3s: {e}")
                await asyncio.sleep(3.0)
