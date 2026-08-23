import sys
import os

# Forzar codificación UTF-8 en Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import asyncio
import signal

# Habilitar motor de eventos ultra-rápido uvloop en producción Linux (Render / AWS)
if sys.platform != "win32":
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass

from src.config import config
from src.utils.logger import get_logger, console
from src.utils.dns_resolver import setup_smart_dns

# Configurar DNS inteligente con fallback DoH
setup_smart_dns()

from src.feeds.multi_feed import MultiExchangePriceFeed
from src.feeds.polymarket_feed import PolymarketFeed
from src.engine.arbitrage_detector import ArbitrageDetector
from src.engine.paper_trader import PaperTradingEngine
from src.engine.real_trader import RealTradingEngine
from src.engine.dashboard import Dashboard
from src.engine.web_server import BotWebServer

logger = get_logger("Main")

class BotApp:
    """
    Aplicación Principal del Bot de Arbitraje de Latencia y Market Making para Polymarket:
    Soporta ejecución tanto en Modo Simulado (Paper Trading) como en Modo Real (CLOB Polygon).
    """
    def __init__(self):
        self.price_feed = MultiExchangePriceFeed()
        self.polymarket_feed = PolymarketFeed()
        
        self.arbitrage_detector = ArbitrageDetector(
            price_feed=self.price_feed,
            polymarket=self.polymarket_feed
        )
        
        # Seleccionar motor de trading (Dinero Real prioritario si hay clave privada)
        if config.polymarket_private_key and not (os.getenv("SIMULATION_MODE", "").lower() == "true" and not config.polymarket_private_key):
            logger.info("🔴 Inicializando Motor de Trading en DINERO REAL (Polymarket CLOB Polygon)")
            self.trader = RealTradingEngine(
                price_feed=self.price_feed,
                polymarket=self.polymarket_feed
            )
        else:
            logger.info("🧪 Inicializando Motor de Simulación (Paper Trading)")
            self.trader = PaperTradingEngine(
                polymarket_feed=self.polymarket_feed,
                price_feed=self.price_feed
            )
        
        self.dashboard = Dashboard(
            price_feed=self.price_feed,
            polymarket=self.polymarket_feed,
            trader=self.trader,
            detector=self.arbitrage_detector
        )

        self.web_server = BotWebServer(
            price_feed=self.price_feed,
            polymarket=self.polymarket_feed,
            trader=self.trader,
            detector=self.arbitrage_detector
        )
        
        self._running = False

    async def _strategy_loop(self):
        """Bucle de alta frecuencia para evaluar señales y gestionar posiciones abiertas"""
        logger.info("⚡ Bucle de estrategia de market making iniciado (50ms scan loop).")
        while self._running:
            try:
                # 1. Evaluar si hay desfases o spreads explotables
                signals = self.arbitrage_detector.check_opportunities()
                for sig in signals:
                    asyncio.create_task(self.trader.execute_signal(sig))

                # 2. Gestionar salidas de posiciones abiertas (Strict Profit Guard)
                self.trader.evaluate_open_positions()

                # Escaneo cada 50 milisegundos
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Error en strategy_loop: {e}")
                await asyncio.sleep(0.5)

    async def start(self):
        self._running = True
        console.print(
            f"[bold cyan]=====================================================\n"
            f"   POLYMARKET QUANTITATIVE MARKET MAKER v2.0.0\n"
            f"   Modo: {'[green]DEMO / PAPER TRADING (0 Riesgo)[/green]' if config.simulation_mode else '[bold red]🔴 DINERO REAL (Polymarket CLOB Polygon)[/bold red]'}\n"
            f"=====================================================[/bold cyan]"
        )

        tasks = [
            asyncio.create_task(self.price_feed.start()),
            asyncio.create_task(self.polymarket_feed.start()),
            asyncio.create_task(self._strategy_loop()),
            asyncio.create_task(self.dashboard.start()),
            asyncio.create_task(self.web_server.start())
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

    async def stop(self):
        logger.info("Cerrando servicios del bot...")
        self._running = False
        await self.price_feed.stop()
        await self.polymarket_feed.stop()
        await self.dashboard.stop()
        await self.web_server.stop()
        logger.info("Todos los servicios detenidos correctamente.")

async def main():
    app = BotApp()

    loop = asyncio.get_running_loop()

    def _signal_handler():
        logger.info("Señal de terminación recibida. Iniciando apagado...")
        asyncio.create_task(app.stop())

    if sys.platform != "win32":
        for s in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(s, _signal_handler)

    try:
        await app.start()
    except (KeyboardInterrupt, SystemExit):
        await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
