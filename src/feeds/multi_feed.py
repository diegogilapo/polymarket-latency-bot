import asyncio
import json
import time
from collections import deque
from typing import Dict, List, Callable, Optional, Any
import websockets
from src.config import config
from src.utils.logger import get_logger

from src.utils.fast_json import fast_loads, fast_dumps

logger = get_logger("MultiAssetFeed")

# Mapeo de símbolos por exchange (15 Criptomonedas)
ASSET_MAPPINGS = {
    "Coinbase": {
        "BTC-USD": "BTC",
        "ETH-USD": "ETH",
        "SOL-USD": "SOL",
        "DOGE-USD": "DOGE",
        "XRP-USD": "XRP",
        "ADA-USD": "ADA",
        "AVAX-USD": "AVAX",
        "LINK-USD": "LINK",
        "NEAR-USD": "NEAR",
        "SUI-USD": "SUI",
        "SHIB-USD": "SHIB",
        "LTC-USD": "LTC",
        "DOT-USD": "DOT"
    },
    "Kraken": {
        "XBT/USD": "BTC",
        "ETH/USD": "ETH",
        "SOL/USD": "SOL",
        "XDG/USD": "DOGE",
        "XRP/USD": "XRP",
        "ADA/USD": "ADA",
        "AVAX/USD": "AVAX",
        "LINK/USD": "LINK",
        "NEAR/USD": "NEAR",
        "SUI/USD": "SUI",
        "PEPE/USD": "PEPE",
        "SHIB/USD": "SHIB",
        "LTC/USD": "LTC",
        "DOT/USD": "DOT"
    },
    "Binance.US": {
        "BTCUSDT": "BTC",
        "ETHUSDT": "ETH",
        "SOLUSDT": "SOL",
        "DOGEUSDT": "DOGE",
        "XRPUSDT": "XRP",
        "ADAUSDT": "ADA",
        "AVAXUSDT": "AVAX",
        "LINKUSDT": "LINK",
        "BNBUSDT": "BNB",
        "NEARUSDT": "NEAR",
        "SUIUSDT": "SUI",
        "PEPEUSDT": "PEPE",
        "SHIBUSDT": "SHIB",
        "LTCUSDT": "LTC",
        "DOTUSDT": "DOT"
    }
}

class MultiExchangePriceFeed:
    """
    Agregador multi-activo y multi-exchange en tiempo real acelerado con SIMD:
    Soporta BTC, ETH, SOL, DOGE y XRP simultáneamente.
    """
    def __init__(self):
        self.assets = config.monitored_assets
        # Estructura: self.asset_prices[asset][exchange] = price
        self.asset_prices: Dict[str, Dict[str, float]] = {
            a: {"Coinbase": 0.0, "Kraken": 0.0, "Binance.US": 0.0}
            for a in self.assets
        }
        self.consensus_prices: Dict[str, float] = {a: 0.0 for a in self.assets}
        self.last_update_times: Dict[str, Dict[str, float]] = {
            a: {"Coinbase": 0.0, "Kraken": 0.0, "Binance.US": 0.0}
            for a in self.assets
        }
        self.is_connected: Dict[str, bool] = {
            "Coinbase": False,
            "Kraken": False,
            "Binance.US": False
        }
        self.price_history: Dict[str, deque] = {a: deque(maxlen=600) for a in self.assets}
        self._running: bool = False
        self._callbacks: List[Callable[[str, float, float], None]] = []

    @property
    def current_price(self) -> float:
        return self.get_price("BTC")

    def register_callback(self, cb: Callable[[str, float, float], None]):
        self._callbacks.append(cb)

    def record_tick(self, asset: str, exchange: str, price: float):
        if price <= 0 or asset not in self.assets:
            return

        now = time.time()
        self.asset_prices[asset][exchange] = price
        self.last_update_times[asset][exchange] = now

        valid_prices = [
            p for exch, p in self.asset_prices[asset].items()
            if p > 0 and (now - self.last_update_times[asset][exch]) < 10.0
        ]

        if valid_prices:
            self.consensus_prices[asset] = sum(valid_prices) / len(valid_prices)
        else:
            self.consensus_prices[asset] = price

        self.price_history[asset].appendleft((now, self.consensus_prices[asset]))

        pct_delta = self.get_pct_delta(asset, config.momentum_window_seconds)
        for cb in self._callbacks:
            try:
                cb(asset, self.consensus_prices[asset], pct_delta)
            except Exception as e:
                logger.debug(f"Error en callback multi-asset: {e}")

    def get_price(self, asset: str) -> float:
        return self.consensus_prices.get(asset, 0.0)

    def get_price_delta(self, asset: str, seconds_back: float = 5.0) -> float:
        history = self.price_history.get(asset)
        current = self.consensus_prices.get(asset, 0.0)
        if not history or current == 0.0:
            return 0.0
        now = time.time()
        target_ts = now - seconds_back
        old_price = current
        for ts, p in history:
            if ts <= target_ts:
                old_price = p
                break
        return current - old_price

    def get_pct_delta(self, asset: str, seconds_back: float = 5.0) -> float:
        current = self.consensus_prices.get(asset, 0.0)
        if current == 0.0:
            return 0.0
        delta = self.get_price_delta(asset, seconds_back)
        return delta / current

    def get_velocity(self, asset: str) -> float:
        delta = self.get_price_delta(asset, config.momentum_window_seconds)
        if config.momentum_window_seconds > 0:
            return delta / config.momentum_window_seconds
        return 0.0

    async def start(self):
        self._running = True
        logger.info(f"Iniciando feeds multi-activo ultra-rápidos para {', '.join(self.assets)}...")
        await asyncio.gather(
            self._feed_coinbase(),
            self._feed_kraken(),
            self._feed_binance_us(),
            return_exceptions=True
        )

    async def stop(self):
        self._running = False
        logger.info("Deteniendo feeds multi-activo...")

    async def _feed_coinbase(self):
        product_ids = list(ASSET_MAPPINGS["Coinbase"].keys())
        while self._running:
            try:
                async with websockets.connect(config.coinbase_ws_url, ping_interval=20, ping_timeout=10) as ws:
                    sub = {"type": "subscribe", "product_ids": product_ids, "channels": ["ticker"]}
                    await ws.send(fast_dumps(sub))
                    self.is_connected["Coinbase"] = True
                    logger.info(f"🟢 Coinbase WS conectado con parser SIMD ({len(product_ids)} activos)")
                    async for msg in ws:
                        if not self._running:
                            break
                        d = fast_loads(msg)
                        if d.get("type") == "ticker" and "price" in d:
                            pid = d.get("product_id")
                            asset = ASSET_MAPPINGS["Coinbase"].get(pid)
                            if asset:
                                self.record_tick(asset, "Coinbase", float(d["price"]))
            except Exception:
                self.is_connected["Coinbase"] = False
                await asyncio.sleep(3.0)

    async def _feed_kraken(self):
        kraken_pairs = list(ASSET_MAPPINGS["Kraken"].keys())
        while self._running:
            try:
                async with websockets.connect(config.kraken_ws_url, ping_interval=20, ping_timeout=10) as ws:
                    sub = {"event": "subscribe", "pair": kraken_pairs, "subscription": {"name": "ticker"}}
                    await ws.send(fast_dumps(sub))
                    self.is_connected["Kraken"] = True
                    logger.info(f"🟢 Kraken WS conectado con parser SIMD ({len(kraken_pairs)} activos)")
                    async for msg in ws:
                        if not self._running:
                            break
                        d = fast_loads(msg)
                        if isinstance(d, list) and len(d) > 3:
                            pair = d[3]
                            asset = ASSET_MAPPINGS["Kraken"].get(pair)
                            ticker_data = d[1]
                            if asset and isinstance(ticker_data, dict) and "c" in ticker_data:
                                self.record_tick(asset, "Kraken", float(ticker_data["c"][0]))
            except Exception:
                self.is_connected["Kraken"] = False
                await asyncio.sleep(3.0)

    async def _feed_binance_us(self):
        streams = [f"{k.lower()}@ticker" for k in ASSET_MAPPINGS["Binance.US"].keys()]
        combined_url = f"wss://stream.binance.us:9443/stream?streams={'/'.join(streams)}"
        while self._running:
            try:
                async with websockets.connect(combined_url, ping_interval=20, ping_timeout=10) as ws:
                    self.is_connected["Binance.US"] = True
                    logger.info(f"🟢 Binance.US WS conectado con parser SIMD ({len(streams)} activos)")
                    async for msg in ws:
                        if not self._running:
                            break
                        d = fast_loads(msg)
                        stream_data = d.get("data", d)
                        s = stream_data.get("s", "")
                        asset = ASSET_MAPPINGS["Binance.US"].get(s)
                        if asset and "c" in stream_data:
                            self.record_tick(asset, "Binance.US", float(stream_data["c"]))
            except Exception:
                self.is_connected["Binance.US"] = False
                await asyncio.sleep(3.0)
