import asyncio
import json
import time
import websockets
from src.config import config
from src.utils.logger import get_logger

logger = get_logger("CoinbaseFeed")

class CoinbaseFeed:
    """
    Cliente WebSocket para Coinbase Pro (BTC-USD) para validación cruzada y descubrimiento de precio en EE.UU.
    """
    def __init__(self):
        self.ws_url = config.coinbase_ws_url
        self.current_price: float = 0.0
        self.last_update_ts: float = 0.0
        self._running: bool = False

    async def start(self):
        self._running = True
        logger.info("Iniciando feed WebSocket de Coinbase Pro (BTC-USD)...")
        while self._running:
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as ws:
                    # Suscribirse al canal ticker de BTC-USD
                    subscribe_msg = {
                        "type": "subscribe",
                        "product_ids": ["BTC-USD"],
                        "channels": ["ticker"]
                    }
                    await ws.send(json.dumps(subscribe_msg))
                    logger.info("🟢 Conectado a Coinbase Pro WebSocket (BTC-USD)")

                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if data.get("type") == "ticker" and "price" in data:
                            self.current_price = float(data["price"])
                            self.last_update_ts = time.time()
            except Exception as e:
                logger.warning(f"Reconectando Coinbase en 3s: {e}")
                await asyncio.sleep(3.0)

    async def stop(self):
        self._running = False
        logger.info("Deteniendo feed de Coinbase...")
