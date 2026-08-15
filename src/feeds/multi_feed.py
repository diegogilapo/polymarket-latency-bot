import asyncio
import json
import time
from collections import deque
from typing import Dict, List, Callable, Optional
import websockets
from src.config import config
from src.utils.logger import get_logger

logger = get_logger("MultiFeed")

class MultiExchangePriceFeed:
    """
    Agregador de feeds de precios de Bitcoin multi-exchange en tiempo real:
    - Coinbase Pro (BTC-USD)
    - Kraken (XBT/USD)
    - Binance.US (BTC-USDT)
    - Bitstamp (BTC-USD)
    - Binance Global (cuando no está restringido por geobloqueo)
    """
    def __init__(self):
        self.prices: Dict[str, float] = {
            "Coinbase": 0.0,
            "Kraken": 0.0,
            "Binance.US": 0.0,
            "Bitstamp": 0.0
        }
        self.last_update_times: Dict[str, float] = {}
        self.current_price: float = 0.0
        self.active_source: str = "Iniciando..."
        self.price_history: deque = deque(maxlen=600)
        self._running: bool = False
        self._callbacks: List[Callable[[float, float], None]] = []

    def register_callback(self, cb: Callable[[float, float], None]):
        self._callbacks.append(cb)

    def record_tick(self, source: str, price: float):
        if price <= 0:
            return
        now = time.time()
        self.prices[source] = price
        self.last_update_times[source] = now
        
        # Calcular precio consenso (promedio de los feeds activos en los últimos 3 segundos)
        active_prices = [p for s, p in self.prices.items() if p > 0 and (now - self.last_update_times.get(s, 0)) < 4.0]
        if active_prices:
            self.current_price = sum(active_prices) / len(active_prices)
        else:
            self.current_price = price
            
        self.active_source = source
        self.price_history.appendleft((now, self.current_price))
        
        vel = self.get_velocity()
        for cb in self._callbacks:
            try:
                cb(self.current_price, vel)
            except Exception as e:
                logger.debug(f"Error en callback multi-feed: {e}")

    def get_price_delta(self, seconds_back: float = 5.0) -> float:
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
        delta = self.get_price_delta(config.btc_momentum_window_seconds)
        if config.btc_momentum_window_seconds > 0:
            return delta / config.btc_momentum_window_seconds
        return 0.0

    async def start(self):
        self._running = True
        logger.info("Iniciando agregador de feeds multi-exchange (Coinbase, Kraken, Binance.US, Bitstamp)...")
        await asyncio.gather(
            self._feed_coinbase(),
            self._feed_kraken(),
            self._feed_binance_us(),
            self._feed_bitstamp(),
            return_exceptions=True
        )

    async def stop(self):
        self._running = False
        logger.info("Deteniendo agregador multi-exchange...")

    async def _feed_coinbase(self):
        while self._running:
            try:
                async with websockets.connect(config.coinbase_ws_url, ping_interval=20, ping_timeout=10) as ws:
                    sub = {"type": "subscribe", "product_ids": ["BTC-USD"], "channels": ["ticker"]}
                    await ws.send(json.dumps(sub))
                    logger.info("🟢 Conectado a Coinbase Pro WS")
                    async for msg in ws:
                        if not self._running:
                            break
                        d = json.loads(msg)
                        if d.get("type") == "ticker" and "price" in d:
                            self.record_tick("Coinbase", float(d["price"]))
            except Exception as e:
                logger.debug(f"Reconectando Coinbase en 3s: {e}")
                await asyncio.sleep(3.0)

    async def _feed_kraken(self):
        while self._running:
            try:
                async with websockets.connect("wss://ws.kraken.com", ping_interval=20, ping_timeout=10) as ws:
                    sub = {"event": "subscribe", "pair": ["XBT/USD"], "subscription": {"name": "ticker"}}
                    await ws.send(json.dumps(sub))
                    logger.info("🟢 Conectado a Kraken WS")
                    async for msg in ws:
                        if not self._running:
                            break
                        d = json.loads(msg)
                        if isinstance(d, list) and len(d) > 1 and isinstance(d[1], dict) and "c" in d[1]:
                            self.record_tick("Kraken", float(d[1]["c"][0]))
            except Exception as e:
                logger.debug(f"Reconectando Kraken en 3s: {e}")
                await asyncio.sleep(3.0)

    async def _feed_binance_us(self):
        while self._running:
            try:
                async with websockets.connect("wss://stream.binance.us:9443/ws/btcusdt@trade", ping_interval=20, ping_timeout=10) as ws:
                    logger.info("🟢 Conectado a Binance.US WS")
                    async for msg in ws:
                        if not self._running:
                            break
                        d = json.loads(msg)
                        if "p" in d:
                            self.record_tick("Binance.US", float(d["p"]))
            except Exception as e:
                logger.debug(f"Reconectando Binance.US en 3s: {e}")
                await asyncio.sleep(3.0)

    async def _feed_bitstamp(self):
        while self._running:
            try:
                async with websockets.connect("wss://ws.bitstamp.net", ping_interval=20, ping_timeout=10) as ws:
                    sub = {"event": "bts:subscribe", "data": {"channel": "live_trades_btcusd"}}
                    await ws.send(json.dumps(sub))
                    logger.info("🟢 Conectado a Bitstamp WS")
                    async for msg in ws:
                        if not self._running:
                            break
                        d = json.loads(msg)
                        if d.get("event") == "trade" and "data" in d:
                            self.record_tick("Bitstamp", float(d["data"]["price"]))
            except Exception as e:
                logger.debug(f"Reconectando Bitstamp en 3s: {e}")
                await asyncio.sleep(3.0)
