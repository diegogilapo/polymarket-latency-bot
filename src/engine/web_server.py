import os
import json
import time
from aiohttp import web
from src.config import config
from src.feeds.binance_feed import BinanceFeed
from src.feeds.coinbase_feed import CoinbaseFeed
from src.feeds.polymarket_feed import PolymarketFeed
from src.engine.paper_trader import PaperTradingEngine
from src.utils.logger import get_logger

logger = get_logger("WebServer")

class BotWebServer:
    """
    Servidor web HTTP embebido para satisfacer los requerimientos de Render Web Service
    y permitir monitoreo remoto vía navegador móvil o PC.
    """
    def __init__(
        self,
        binance: BinanceFeed,
        coinbase: CoinbaseFeed,
        polymarket: PolymarketFeed,
        trader: PaperTradingEngine
    ):
        self.binance = binance
        self.coinbase = coinbase
        self.polymarket = polymarket
        self.trader = trader
        self.port = int(os.getenv("PORT", 8080))
        self.app = web.Application()
        self.runner = None
        self.site = None
        
        # Rutas
        self.app.router.add_get("/", self.handle_dashboard)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/api/status", self.handle_api_status)

    async def handle_health(self, request):
        return web.Response(text="OK", status=200)

    async def handle_api_status(self, request):
        data = {
            "status": "running",
            "simulation_mode": config.simulation_mode,
            "btc_binance_futures": self.binance.current_price,
            "btc_coinbase_spot": self.coinbase.current_price,
            "btc_delta_5s": self.binance.get_price_delta(5.0),
            "btc_velocity": self.binance.get_velocity(),
            "active_polymarket_markets": len(self.polymarket.active_markets),
            "balance_usdc": round(self.trader.balance_usdc, 2),
            "total_pnl_usdc": round(self.trader.total_pnl_usdc, 2),
            "closed_trades": self.trader.closed_trades_count,
            "wins": self.trader.wins_count,
            "losses": self.trader.losses_count,
            "open_positions": len(self.trader.open_positions)
        }
        return web.json_response(data)

    async def handle_dashboard(self, request):
        b_price = self.binance.current_price
        b_delta = self.binance.get_price_delta(5.0)
        b_vel = self.binance.get_velocity()
        c_price = self.coinbase.current_price
        pnl = self.trader.total_pnl_usdc
        pnl_color = "#10b981" if pnl >= 0 else "#ef4444"
        delta_color = "#10b981" if b_delta >= 0 else "#ef4444"
        winrate = (self.trader.wins_count / self.trader.closed_trades_count * 100) if self.trader.closed_trades_count > 0 else 0.0

        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Polymarket Latency Bot - Live Monitor</title>
    <meta http-equiv="refresh" content="5">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0b0f19; color: #e2e8f0; padding: 20px; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1e293b; padding-bottom: 15px; margin-bottom: 20px; }}
        .title {{ font-size: 22px; font-weight: 700; color: #38bdf8; display: flex; align-items: center; gap: 8px; }}
        .badge {{ background: #0369a1; color: #e0f2fe; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600; text-transform: uppercase; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .card {{ background: #131c2e; border: 1px solid #1e293b; border-radius: 10px; padding: 16px; }}
        .card-label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
        .card-value {{ font-size: 24px; font-weight: 700; color: #f8fafc; }}
        .card-sub {{ font-size: 12px; margin-top: 4px; color: #64748b; }}
        .table-container {{ background: #131c2e; border: 1px solid #1e293b; border-radius: 10px; padding: 16px; margin-top: 15px; }}
        .table-title {{ font-size: 14px; font-weight: 600; color: #94a3b8; margin-bottom: 12px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #1e293b; }}
        th {{ color: #64748b; font-weight: 600; }}
        .status-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #10b981; margin-right: 6px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">
                <span>🚀</span> Polymarket Latency Bot
            </div>
            <div>
                <span class="badge"><span class="status-dot"></span>{'MODO DEMO' if config.simulation_mode else 'MODO REAL'}</span>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <div class="card-label">BTC Binance (Futures)</div>
                <div class="card-value">${b_price:,.2f}</div>
                <div class="card-sub" style="color: {delta_color}">Δ5s: {b_delta:+,.2f} USD | Vel: {b_vel:+.1f} $/s</div>
            </div>
            <div class="card">
                <div class="card-label">BTC Coinbase (Spot)</div>
                <div class="card-value">${c_price:,.2f}</div>
                <div class="card-sub">Validación cruzada US</div>
            </div>
            <div class="card">
                <div class="card-label">Balance Virtual (USDC)</div>
                <div class="card-value">${self.trader.balance_usdc:,.2f}</div>
                <div class="card-sub">Inicial: ${self.trader.initial_balance:,.2f} USDC</div>
            </div>
            <div class="card">
                <div class="card-label">PnL Acumulado</div>
                <div class="card-value" style="color: {pnl_color}">{pnl:+,.2f} USDC</div>
                <div class="card-sub">WinRate: {winrate:.1f}% ({self.trader.wins_count}W / {self.trader.losses_count}L)</div>
            </div>
        </div>

        <div class="table-container">
            <div class="table-title">MERCADOS POLYMARKET MONITORIZADOS ({len(self.polymarket.active_markets)} ACTIVOS)</div>
            <table>
                <thead>
                    <tr>
                        <th>Pregunta de Mercado</th>
                        <th>Best Bid</th>
                        <th>Best Ask</th>
                        <th>Spread</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join([f"<tr><td>{m.question[:60]}...</td><td>{m.yes_book.best_bid:.3f}</td><td>{m.yes_book.best_ask:.3f}</td><td>{abs(m.yes_book.best_ask - m.yes_book.best_bid):.3f}</td></tr>" for m in list(self.polymarket.active_markets.values())[:5]]) if self.polymarket.active_markets else "<tr><td colspan='4'>Sincronizando libros de órdenes...</td></tr>"}
                </tbody>
            </table>
        </div>
        
        <p style="text-align: center; color: #475569; font-size: 11px; margin-top: 20px;">
            Auto-refresco cada 5 segundos • Latencia de red simulada: {config.simulated_network_latency_ms}ms
        </p>
    </div>
</body>
</html>"""
        return web.Response(text=html, content_type="text/html")

    async def start(self):
        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, "0.0.0.0", self.port)
            await self.site.start()
            logger.info(f"🌐 Servidor Web HTTP activo en el puerto {self.port} (Listo para Render Web Service)")
        except Exception as e:
            logger.error(f"Error iniciando servidor web: {e}")

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
            logger.info("Servidor web detenido.")
