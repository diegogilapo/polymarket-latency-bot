import os
import asyncio
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
    Servidor Web y Dashboard HTTP para Render:
    - Endpoint /health para el Health Check de Render.
    - Endpoint /api/status con métricas en formato JSON.
    - Dashboard HTML interactivo en tiempo real con cotizaciones de Market Making.
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
        self.app = web.Application()
        self.runner = None
        self.site = None
        self.port = int(os.getenv("PORT", "10000"))

        # Rutas HTTP
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_head("/health", self.handle_health)
        self.app.router.add_get("/", self.handle_dashboard)
        self.app.router.add_head("/", self.handle_dashboard)
        self.app.router.add_get("/api/status", self.handle_api_status)

    async def handle_health(self, request):
        return web.Response(text="OK", status=200)

    async def handle_api_status(self, request):
        diag = self.detector.get_scan_diagnosis()
        data = {
            "status": "running",
            "simulation_mode": config.simulation_mode,
            "monitored_assets": config.monitored_assets,
            "consensus_prices": self.price_feed.consensus_prices,
            "scan_verdict": diag["verdict"],
            "active_polymarket_markets": len(self.polymarket.active_markets),
            "balance_usdc": round(self.trader.balance_usdc, 2),
            "total_pnl_usdc": round(self.trader.total_pnl_usdc, 2),
            "closed_trades": self.trader.closed_trades_count,
            "wins": self.trader.wins_count,
            "losses": self.trader.losses_count,
            "active_inventories": len(self.trader.inventories)
        }
        return web.json_response(data)

    async def handle_dashboard(self, request):
        if request.method == "HEAD":
            return web.Response(status=200, content_type="text/html")

        diag = self.detector.get_scan_diagnosis()
        pnl = self.trader.total_pnl_usdc
        pnl_color = "#10b981" if pnl >= 0 else "#ef4444"
        winrate = (self.trader.wins_count / self.trader.closed_trades_count * 100) if self.trader.closed_trades_count > 0 else 100.0

        # Tarjetas de Criptomonedas (BTC, ETH, SOL, DOGE, XRP)
        crypto_cards = ""
        for a in config.monitored_assets:
            p = self.price_feed.get_price(a)
            pct = self.price_feed.get_pct_delta(a, config.momentum_window_seconds) * 100.0
            pct_col = "#10b981" if pct >= 0 else "#ef4444"
            p_str = f"${p:,.4f}" if p < 1.0 else f"${p:,.2f}"
            crypto_cards += f"""<div class="card">
                <div class="card-label">{a} Spot Consenso</div>
                <div class="card-value">{p_str if p > 0 else '---'}</div>
                <div class="card-sub" style="color: {pct_col}; font-weight:600;">Δ3s: {pct:+.2f}%</div>
            </div>"""

        # Filas de mercados de Market Making
        market_rows = ""
        evals = diag.get("market_evals", [])
        for ev in evals[:15]:
            fair = ev["fair_price"]
            bid = ev["our_bid"]
            ask = ev["our_ask"]
            spread = ev["spread_captured"]
            m_type = ev["mispricing_type"]

            if m_type == "CHEAP_ASK":
                badge = '<span class="badge" style="background:#065f46;color:#a7f3d0;">COMPRA BARATA</span>'
            elif m_type == "EXPENSIVE_BID":
                badge = '<span class="badge" style="background:#991b1b;color:#fecaca;">VENTA CARA</span>'
            else:
                badge = '<span class="badge" style="background:#1e1b4b;color:#38bdf8;">SPREAD MAKER</span>'

            market_rows += f"""<tr>
                <td><span class="badge" style="background:#312e81;color:#c7d2fe;">{ev.get('asset', 'CRYPTO')}</span></td>
                <td><strong>{ev['question'][:55]}...</strong></td>
                <td style="color:#38bdf8;font-weight:600;">${fair:.3f}</td>
                <td style="color:#10b981;font-weight:700;">${bid:.3f}</td>
                <td style="color:#f87171;font-weight:700;">${ask:.3f}</td>
                <td style="color:#fbbf24;font-weight:700;">+{spread*100:.1f}¢</td>
                <td>{badge}</td>
            </tr>"""

        if not market_rows:
            market_rows = "<tr><td colspan='7' style='text-align:center;'>Sincronizando libros de órdenes de Polymarket...</td></tr>"

        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Polymarket Quantitative Market Maker - Maker Only</title>
    <meta http-equiv="refresh" content="5">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #1e293b; }}
        .title {{ font-size: 20px; font-weight: 700; display: flex; align-items: center; gap: 8px; color: #38bdf8; }}
        .badge {{ padding: 4px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 24px; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 16px; border: 1px solid #334155; }}
        .card-label {{ font-size: 11px; font-weight: 600; color: #94a3b8; text-transform: uppercase; margin-bottom: 6px; }}
        .card-value {{ font-size: 20px; font-weight: 700; color: #f8fafc; }}
        .card-sub {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
        .verdict-box {{ background: #1e293b; border-left: 4px solid #10b981; padding: 14px 18px; border-radius: 8px; margin-bottom: 24px; font-size: 14px; }}
        .table-container {{ background: #1e293b; border-radius: 12px; padding: 16px; border: 1px solid #334155; overflow-x: auto; }}
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
                <span>🏛️</span> Polymarket Quantitative Market Maker
            </div>
            <div>
                <span class="badge" style="background:#0369a1;color:#e0f2fe;"><span class="status-dot"></span>{'MODO DEMO' if config.simulation_mode else 'MODO REAL'}</span>
            </div>
        </div>

        <div class="verdict-box">
            <strong>🔍 Diagnóstico del Market Maker:</strong> {diag['verdict']}
        </div>

        <div class="grid">
            {crypto_cards}
        </div>

        <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));">
            <div class="card">
                <div class="card-label">Balance Virtual (USDC)</div>
                <div class="card-value">${self.trader.balance_usdc:,.2f}</div>
                <div class="card-sub">Inicial: ${self.trader.initial_balance:,.2f} USDC</div>
            </div>
            <div class="card">
                <div class="card-label">PnL de Spread Acumulado</div>
                <div class="card-value" style="color: {pnl_color}">{pnl:+,.2f} USDC</div>
                <div class="card-sub">WinRate: {winrate:.1f}% ({self.trader.wins_count}W / {self.trader.losses_count}L)</div>
            </div>
            <div class="card">
                <div class="card-label">Mercados Cotizando en Vivo</div>
                <div class="card-value">{len(self.polymarket.active_markets)} libros activos</div>
                <div class="card-sub">Spread Objetivo: +{config.target_spread_cents*100:.1f}¢ por ciclo</div>
            </div>
        </div>

        <div class="table-container">
            <div class="table-title">COTIZACIÓN LÍMITE Y RADAR DE SPREAD ({len(self.polymarket.active_markets)} MERCADOS)</div>
            <table>
                <thead>
                    <tr>
                        <th>Cripto</th>
                        <th>Mercado</th>
                        <th>Fair Value</th>
                        <th>Límite Compra (Bid)</th>
                        <th>Límite Venta (Ask)</th>
                        <th>Spread Capturado</th>
                        <th>Oportunidad</th>
                    </tr>
                </thead>
                <tbody>
                    {market_rows}
                </tbody>
            </table>
        </div>
        
        <p style="text-align: center; color: #475569; font-size: 11px; margin-top: 20px;">
            Auto-refresco cada 5s • Rol: 100% MAKER • Aceleración SIMD activa
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
            logger.info(f"🌐 Servidor Web HTTP activo en el puerto {self.port}")
        except Exception as e:
            logger.error(f"Error al iniciar servidor web: {e}")

    async def stop(self):
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logger.info("Servidor Web detenido.")
