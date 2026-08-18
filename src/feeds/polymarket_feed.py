import asyncio
import json
import time
import re
import ssl
import certifi
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import aiohttp
import websockets
from src.config import config
from src.utils.logger import get_logger
from src.utils.dns_resolver import get_aiohttp_connector

logger = get_logger("PolymarketFeed")

@dataclass
class OrderBookLevel:
    price: float
    size: float

@dataclass
class TokenOrderBook:
    token_id: str
    outcome: str
    best_bid: float = 0.0
    best_bid_size: float = 0.0
    best_ask: float = 1.0
    best_ask_size: float = 0.0
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)
    last_update_ts: float = 0.0

def detect_market_asset(text: str) -> Optional[str]:
    """Detecta a qué criptoactivo corresponde el mercado usando límites de palabra estricto"""
    t = text.lower()
    if re.search(r"\b(bitcoin|btc)\b", t):
        return "BTC"
    elif re.search(r"\b(ethereum|ether|eth)\b", t):
        return "ETH"
    elif re.search(r"\b(solana|sol)\b", t):
        return "SOL"
    elif re.search(r"\b(dogecoin|doge)\b", t):
        return "DOGE"
    elif re.search(r"\b(ripple|xrp)\b", t):
        return "XRP"
    return None

@dataclass
class PolymarketMarket:
    condition_id: str
    question: str
    end_date_iso: str
    yes_token_id: str
    no_token_id: str
    asset: str
    initial_prob: float = 0.50
    yes_book: TokenOrderBook = field(init=False)
    no_book: TokenOrderBook = field(init=False)
    
    def __post_init__(self):
        self.yes_book = TokenOrderBook(token_id=self.yes_token_id, outcome="YES")
        self.no_book = TokenOrderBook(token_id=self.no_token_id, outcome="NO")

class PolymarketFeed:
    """
    Gestiona el descubrimiento de mercados de alta sensibilidad y liquidez en la Zona Activa
    (BTC, ETH, SOL, DOGE, XRP) y la suscripción en tiempo real al WebSocket de Polymarket CLOB.
    """
    def __init__(self):
        self.gamma_url = config.polymarket_gamma_url
        self.clob_ws_url = config.polymarket_clob_ws_url
        self.clob_http_url = config.polymarket_clob_http_url
        self.active_markets: Dict[str, PolymarketMarket] = {}
        self.token_to_market: Dict[str, PolymarketMarket] = {}
        self._running: bool = False

    async def fetch_active_crypto_markets(self) -> List[PolymarketMarket]:
        """
        Descubre y prioriza mercados en la Zona Activa de Probabilidad (0.06 - 0.94)
        ordenados por máxima sensibilidad y volumen.
        """
        discovered: List[PolymarketMarket] = []
        seen_conditions = set()

        urls = [
            f"{self.gamma_url}/events?closed=false&limit=100&order=volume24hr&ascending=false",
            f"{self.gamma_url}/events?tag_slug=crypto&closed=false&limit=100",
            f"{self.gamma_url}/events?closed=false&limit=100&search=bitcoin",
            f"{self.gamma_url}/events?closed=false&limit=100&search=ethereum",
            f"{self.gamma_url}/events?closed=false&limit=100&search=solana",
            f"{self.gamma_url}/events?closed=false&limit=100&search=price"
        ]

        try:
            connector = get_aiohttp_connector()
            async with aiohttp.ClientSession(connector=connector) as session:
                for url in urls:
                    try:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                            if resp.status != 200:
                                continue
                            events = await resp.json()
                            if not isinstance(events, list):
                                continue

                            for ev in events:
                                title = ev.get("title", "")
                                desc = ev.get("description", "")
                                markets = ev.get("markets", [])

                                for m in markets:
                                    if not m.get("active") or m.get("closed"):
                                        continue

                                    cond_id = m.get("conditionId", m.get("id", ""))
                                    if not cond_id or cond_id in seen_conditions:
                                        continue

                                    question = m.get("question", title)
                                    full_text = f"{title} {question} {desc}"
                                    asset = detect_market_asset(question) or detect_market_asset(full_text)

                                    if not asset:
                                        continue

                                    # Obtener precio estimado para filtrar zona activa
                                    prices_raw = m.get("outcomePrices")
                                    yes_price = 0.50
                                    if prices_raw:
                                        if isinstance(prices_raw, str):
                                            try: prices_list = json.loads(prices_raw)
                                            except Exception: prices_list = []
                                        else:
                                            prices_list = prices_raw
                                        if prices_list and len(prices_list) >= 1:
                                            try: yes_price = float(prices_list[0])
                                            except Exception: yes_price = 0.50

                                    # FILTRO DE ORO: Solo incluir contratos en la Zona Activa (0.05 a 0.95)
                                    # Descartar contratos basura de $0.001 o $0.999 sin volatilidad
                                    if not (0.05 <= yes_price <= 0.95):
                                        continue

                                    clob_tokens = m.get("clobTokenIds")
                                    if isinstance(clob_tokens, str):
                                        try:
                                            clob_tokens = json.loads(clob_tokens)
                                        except Exception:
                                            clob_tokens = []

                                    if not clob_tokens or len(clob_tokens) < 2:
                                        tokens = m.get("tokens", [])
                                        if len(tokens) >= 2:
                                            clob_tokens = [tokens[0].get("token_id"), tokens[1].get("token_id")]

                                    if clob_tokens and len(clob_tokens) >= 2:
                                        yes_token = str(clob_tokens[0])
                                        no_token = str(clob_tokens[1])
                                        end_date = m.get("endDate", "")

                                        pm_market = PolymarketMarket(
                                            condition_id=cond_id,
                                            question=question,
                                            end_date_iso=end_date,
                                            yes_token_id=yes_token,
                                            no_token_id=no_token,
                                            asset=asset,
                                            initial_prob=yes_price
                                        )
                                        discovered.append(pm_market)
                                        seen_conditions.add(cond_id)
                                        self.active_markets[cond_id] = pm_market
                                        self.token_to_market[yes_token] = pm_market
                                        self.token_to_market[no_token] = pm_market
                    except Exception as err:
                        logger.debug(f"Error consultando {url}: {err}")

            # Ordenar por proximidad al 50% (máxima sensibilidad Gamma)
            discovered.sort(key=lambda x: abs(x.initial_prob - 0.50))

            unique_assets = set(m.asset for m in discovered)
            logger.info(f"✅ Se descubrieron {len(discovered)} mercados de ALTA SENSIBILIDAD ({', '.join(unique_assets)}) en Zona Activa (0.05-0.95).")
            for dm in discovered[:6]:
                logger.info(f"  • [{dm.asset}] P: {dm.initial_prob:.2f} | {dm.question[:55]}...")
        except Exception as e:
            logger.error(f"Excepción al buscar mercados en Gamma API: {e}")
        
        return discovered

    async def update_book_via_rest(self, token_id: str):
        """Actualiza el libro de órdenes por REST para bootstrapping inicial o refresco"""
        try:
            url = f"{self.clob_http_url}/book?token_id={token_id}"
            connector = get_aiohttp_connector()
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        book_data = await resp.json()
                        self._process_book_data(token_id, book_data)
        except Exception as e:
            logger.debug(f"Error libro REST {token_id[:10]}: {e}")

    def _process_book_data(self, token_id: str, data: dict):
        """Procesa datos crudos del libro de órdenes y actualiza el objeto TokenOrderBook"""
        market = self.token_to_market.get(token_id)
        if not market:
            return

        book = market.yes_book if market.yes_token_id == token_id else market.no_book
        
        bids_raw = data.get("bids", [])
        asks_raw = data.get("asks", [])
        
        book.bids = [OrderBookLevel(price=float(b.get("price", 0)), size=float(b.get("size", 0))) for b in bids_raw]
        book.asks = [OrderBookLevel(price=float(a.get("price", 0)), size=float(a.get("size", 0))) for a in asks_raw]
        
        book.bids.sort(key=lambda x: x.price, reverse=True)
        book.asks.sort(key=lambda x: x.price)
        
        if book.bids:
            book.best_bid = book.bids[0].price
            book.best_bid_size = book.bids[0].size
        else:
            book.best_bid = 0.0
            book.best_bid_size = 0.0

        if book.asks:
            book.best_ask = book.asks[0].price
            book.best_ask_size = book.asks[0].size
        else:
            book.best_ask = 1.0
            book.best_ask_size = 0.0

        book.last_update_ts = time.time()

    async def start(self):
        self._running = True
        logger.info("Iniciando Polymarket Feed...")
        
        # 1. Buscar mercados activos en la zona de sensibilidad
        await self.fetch_active_crypto_markets()

        # 2. Suscribir a TODOS los tokens descubiertos (hasta 200 tokens en lotes)
        all_tokens = list(self.token_to_market.keys())[:200]
        
        # Inicializar los primeros 25 por REST rápidamente
        for tid in all_tokens[:25]:
            await self.update_book_via_rest(tid)

        # 3. Iniciar streaming WebSocket completo
        await asyncio.gather(
            self._listen_clob_ws(all_tokens),
            self._periodic_rest_refresh(all_tokens[:40]),
            return_exceptions=True
        )

    async def _listen_clob_ws(self, token_ids: List[str]):
        """Mantiene la conexión WebSocket con el CLOB de Polymarket para TODOS los tokens activos"""
        if not token_ids:
            return

        ssl_ctx = ssl.create_default_context(cafile=certifi.where())

        while self._running:
            try:
                async with websockets.connect(
                    self.clob_ws_url,
                    ssl=ssl_ctx,
                    ping_interval=20,
                    ping_timeout=10,
                    additional_headers={"User-Agent": "Mozilla/5.0"}
                ) as ws:
                    # Suscripción por lotes de 100 para estabilidad
                    for chunk_start in range(0, len(token_ids), 100):
                        chunk = token_ids[chunk_start:chunk_start + 100]
                        sub_payload = {
                            "assets_ids": chunk,
                            "type": "market"
                        }
                        await ws.send(json.dumps(sub_payload))
                        await asyncio.sleep(0.1)

                    logger.info(f"🟢 Suscrito al WebSocket del CLOB de Polymarket ({len(token_ids)} tokens activos en streaming)")

                    async for msg in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(msg)
                            if isinstance(data, list):
                                for item in data:
                                    self._handle_ws_event(item)
                            elif isinstance(data, dict):
                                self._handle_ws_event(data)
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"Reconectando Polymarket CLOB WS en 3s: {e}")
                await asyncio.sleep(3.0)

    def _handle_ws_event(self, event: dict):
        event_type = event.get("event_type") or event.get("type")
        asset_id = event.get("asset_id") or event.get("market")
        
        if not asset_id:
            return

        if event_type in ("book", "price_change", "order_book_update") or "bids" in event or "asks" in event:
            self._process_book_data(str(asset_id), event)

    async def _periodic_rest_refresh(self, token_ids: List[str]):
        """Refresca periódicamente por REST para garantizar libros siempre sincronizados"""
        while self._running:
            try:
                for tid in token_ids:
                    await self.update_book_via_rest(tid)
                    await asyncio.sleep(0.08)
                await asyncio.sleep(3.0)
            except Exception as e:
                await asyncio.sleep(3.0)

    async def stop(self):
        self._running = False
        logger.info("Deteniendo Polymarket Feed...")
