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
from src.config import config
from src.utils.logger import get_logger, console
from src.utils.dns_resolver import setup_smart_dns

# Configurar DNS inteligente con fallback DoH
setup_smart_dns()

from src.feeds.binance_feed import BinanceFeed
from src.feeds.coinbase_feed import CoinbaseFeed
from src.feeds.polymarket_feed import PolymarketFeed
from src.engine.arbitrage_detector import ArbitrageDetector
from src.engine.paper_trader import PaperTradingEngine
from src.engine.dashboard import Dashboard

logger = get_logger("Main")

class BotApp:
    def __init__(self):
        self.binance_feed = BinanceFeed()
        self.coinbase_feed = CoinbaseFeed()
        self.polymarket_feed = PolymarketFeed()
        
        self.arbitrage_detector = ArbitrageDetector(
            binance=self.binance_feed,
            coinbase=self.coinbase_feed,
            polymarket=self.polymarket_feed
        )
        
        self.paper_trader = PaperTradingEngine(
            polymarket_feed=self.polymarket_feed,
            binance_feed=self.binance_feed
        )
        
        self.dashboard = Dashboard(
            binance=self.binance_feed,
            coinbase=self.coinbase_feed,
            polymarket=self.polymarket_feed,
            trader=self.paper_trader
        )
        
        self._running = False

    async def _strategy_loop(self):
        """Bucle de alta frecuencia para evaluar señales y gestionar posiciones abiertas"""
        logger.info("⚡ Bucle de estrategia de arbitraje iniciado (50ms scan loop).")
        while self._running:
            try:
                # 1. Evaluar si hay desfases explotables
                signals = self.arbitrage_detector.check_opportunities()
                for sig in signals:
                    if config.simulation_mode:
                        # Ejecutar en Paper Trading
                        asyncio.create_task(self.paper_trader.execute_signal(sig))
                    else:
                        logger.warning(f"⚠️ Señal detectada en modo real: {sig}")

                # 2. Gestionar salidas de posiciones abiertas (TP / SL / Timeout)
                self.paper_trader.evaluate_open_positions()

                # Escaneo cada 50 milisegundos
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Error en strategy_loop: {e}")
                await asyncio.sleep(0.5)

    async def start(self):
        self._running = True
        console.print(
            f"[bold cyan]=====================================================\n"
            f"   POLYMARKET BTC LATENCY ARBITRAGE BOT v1.0.0\n"
            f"   Modo: {'[green]DEMO / PAPER TRADING (0 Riesgo)[/green]' if config.simulation_mode else '[red]DINERO REAL[/red]'}\n"
            f"=====================================================[/bold cyan]"
        )

        tasks = [
            asyncio.create_task(self.binance_feed.start()),
            asyncio.create_task(self.coinbase_feed.start()),
            asyncio.create_task(self.polymarket_feed.start()),
            asyncio.create_task(self._strategy_loop()),
            asyncio.create_task(self.dashboard.start())
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Tareas canceladas por detención del bot.")

    async def stop(self):
        logger.info("Cerrando feeds y guardando estado...")
        self._running = False
        await self.binance_feed.stop()
        await self.coinbase_feed.stop()
        await self.polymarket_feed.stop()
        await self.dashboard.stop()

def handle_exit(loop, app):
    logger.info("Recibida señal de terminación (SIGINT/SIGTERM). Apagando bot...")
    asyncio.create_task(app.stop())

async def main():
    app = BotApp()
    
    # Manejadores de señal para apagado limpio
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: handle_exit(loop, app))
        except NotImplementedError:
            # En Windows add_signal_handler puede no estar disponible
            pass

    try:
        await app.start()
    except KeyboardInterrupt:
        logger.info("Detención manual por teclado.")
    finally:
        await app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
