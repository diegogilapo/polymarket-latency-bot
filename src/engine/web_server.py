import os
import json
import time
from aiohttp import web
from src.config import config
from src.feeds.multi_feed import MultiExchangePriceFeed
from src.feeds.polymarket_feed import PolymarketFeed
from src.engine.paper_trader import PaperTradingEngine
from src.engine.arbitrage_detector import ArbitrageDetector
from src.utils.logger import get_logger

logger = get_logger("WebServer")

class BotWebServer:
    """
    Servidor web HTTP embebido para satisfacer los requerimientos de Render Web Service
    y permitir monitoreo remoto vía navegador móvil o PC con diagnóstico transparente.
    """
    def __init__(
        self,
        price_feed: MultiExchangePriceFeed,
        polymarket: PolymarketFeed,
        trader: PaperTradingEngine,
        detector: ArbitrageDetector
    ):
        self.price_feed = price_feed
        self.polymarket = polymarket
        self.trader = trader
        self.detector = detector
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
        diag = self.detector.get_scan_diagnosis()
        data = {
            "status": "running",
            "simulation_mode": config.simulation_mode,
            "btc_consensus_price": self.price_feed.current_price,
            "exchange_prices": self.price_feed.prices,
            "btc_delta_5s": self.price_feed.get_price_delta(5.0),
            "btc_velocity": self.price_feed.get_velocity(),
            "scan_verdict": diag["verdict"],
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
        diag = self.detector.get_scan_diagnosis()
        b_price = diag["btc_price"]
        b_delta = diag["btc_delta_5s"]
        b_vel = diag["btc_velocity"]
        pnl = self.trader.total_pnl_usdc
        pnl_color = "#10b981" if pnl >= 0 else "#ef4444"
        delta_color = "#10b981" if b_delta >= 0 else "#ef4444"
        winrate = (self.trader.wins_count / self.trader.closed_trades_count * 100) if self.trader.closed_trades_count > 0 else 0.0

        # Tarjetas de exchanges
        exchange_cards = "".join([
            f"""<div class="card">
                <div class="card-label">{exch}</div>
                <div class="card-value">${p:,.2f}</div>
                <div class="card-sub" style="color: {'#10b981' if p>0 else '#64748b'}">{'● En vivo' if p>0 else '○ Sincronizando'}</div>
            </div>"""
            for exch, p in self.price_feed.prices.items()
        ])

        # Filas de mercados
        market_rows = ""
        evals = diag.get("market_evals", [])
        for ev in evals[:6]:
            diff = ev["diff"]
            diff_color = "#10b981" if diff >= config.min_price_discrepancy else "#94a3b8"
            signal_badge = '<span class="badge" style="background:#065f46;color:#a7f3d0;">ENTRAR</span>' if ev["is_signal"] else '<span style="color:#64748b;">Esperar</span>'
            market_rows += f"""<tr>
                <td><strong>{ev['question'][:55]}...</strong> <span style="color:#38bdf8;">({ev['outcome']})</span></td>
                <td>{ev['best_bid']:.3f}</td>
                <td>{ev['best_ask']:.3f}</td>
                <td style="color:#38bdf8;font-weight:600;">{ev['fair_value']:.3f}</td>
                <td style="color:{diff_color};font-weight:600;">{diff*100:+.1f}¢</td>
                <td>{signal_badge}</td>
            </tr>"""

        if not market_rows:
            market_rows = "<tr><td colspan='6' style='text-align:center;'>Sincronizando libros de órdenes...</td></tr>"

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
        .container {{ max-width: 960px; margin: 0 auto; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1e293b; padding-bottom: 15px; margin-bottom: 20px; }}
        .title {{ font-size: 22px; font-weight: 700; color: #38bdf8; display: flex; align-items: center; gap: 8px; }}
        .badge {{ background: #0369a1; color: #e0f2fe; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600; text-transform: uppercase; }}
        .verdict-box {{ background: #1e1b4b; border: 1px solid #4338ca; border-radius: 8px; padding: 14px 18px; margin-bottom: 20px; font-size: 14px; color: #e0e7ff; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 20px; }}
        .card {{ background: #131c2e; border: 1px solid #1e293b; border-radius: 10px; padding: 14px; }}
        .card-label {{ font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
        .card-value {{ font-size: 20px; font-weight: 700; color: #f8fafc; }}
        .card-sub {{ font-size: 11px; margin-top: 4px; color: #64748b; }}
        .table-container {{ background: #131c2e; border: 1px solid #1e293b; border-radius: 10px; padding: 16px; margin-top: 15px; }}
        .table-title {{ font-size: 13px; font-weight: 600; color: #94a3b8; margin-bottom: 12px; text-transform: uppercase; }}
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

        <div class="verdict-box">
            <strong>🔍 Diagnóstico del Scanner:</strong> {diag['verdict']}
        </div>

        <div class="grid">
            <div class="card" style="border-color: #38bdf8;">
                <div class="card-label">BTC Consenso Global</div>
                <div class="card-value">${b_price:,.2f}</div>
                <div class="card-sub" style="color: {delta_color}">Δ5s: {b_delta:+,.2f} USD | Vel: {b_vel:+.1f} $/s</div>
            </div>
            {exchange_cards}
        </div>

        <div class="grid">
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
            <div class="card">
                <div class="card-label">Posiciones Abiertas</div>
                <div class="card-value">{len(self.trader.open_positions)} activas</div>
                <div class="card-sub">TP: +{config.take_profit_delta*100:.0f}¢ | SL: -{config.stop_loss_delta*100:.0f}¢</div>
            </div>
        </div>

        <div class="table-container">
            <div class="table-title">MERCADOS POLYMARKET Y MONITOREO DE DESFASES ({len(self.polymarket.active_markets)} ACTIVOS)</div>
            <table>
                <thead>
                    <tr>
                        <th>Mercado & Outcome</th>
                        <th>Best Bid</th>
                        <th>Best Ask</th>
                        <th>Fair Value</th>
                        <th>Desfase (Lag)</th>
                        <th>Acción</th>
                    </tr>
                </thead>
                <tbody>
                    {market_rows}
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
