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
    Servidor Web y Dashboard HTTP en Tiempo Real:
    - Estado de Billetera y PnL.
    - Posiciones y Operaciones Abiertas (Dinero invertido, acciones y ganancia objetivo).
    - Radar de Oportunidades Encontradas.
    - Precios Cripto Spot en Vivo.
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
        open_pos = self.trader.get_open_positions_summary()
        data = {
            "status": "running",
            "simulation_mode": config.simulation_mode,
            "balance_usdc": round(self.trader.balance_usdc, 2),
            "initial_balance_usdc": round(self.trader.initial_balance, 2),
            "total_pnl_usdc": round(self.trader.total_pnl_usdc, 2),
            "closed_trades": self.trader.closed_trades_count,
            "wins": self.trader.wins_count,
            "losses": self.trader.losses_count,
            "open_positions": open_pos,
            "scan_verdict": diag["verdict"],
            "active_polymarket_markets": len(self.polymarket.active_markets)
        }
        return web.json_response(data)

    async def handle_dashboard(self, request):
        if request.method == "HEAD":
            return web.Response(status=200, content_type="text/html")

        diag = self.detector.get_scan_diagnosis()
        pnl = self.trader.total_pnl_usdc
        pnl_color = "#10b981" if pnl >= 0 else "#ef4444"
        winrate = (self.trader.wins_count / self.trader.closed_trades_count * 100) if self.trader.closed_trades_count > 0 else 100.0
        open_pos = self.trader.get_open_positions_summary()

        # 1. Tarjetas de Precios Cripto Spot
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

        # 2. Filas de Posiciones Abiertas
        open_pos_html = ""
        if open_pos:
            rows = ""
            for pos in open_pos:
                rows += f"""<tr>
                    <td><span class="badge" style="background:#854d0e;color:#fef08a;">{pos['asset']}</span></td>
                    <td><strong>{pos['question']}</strong></td>
                    <td style="color:#38bdf8;font-weight:700;">${pos['invested_usdc']:.2f} USDC</td>
                    <td style="color:#94a3b8;">{pos['shares_held']:.1f} sh</td>
                    <td style="color:#38bdf8;">${pos['avg_buy_price']:.3f}</td>
                    <td style="color:#fbbf24;font-weight:700;">${pos['target_sell_price']:.3f}</td>
                    <td style="color:#10b981;font-weight:700;">+${pos['projected_profit_usdc']:.2f} (+{pos['projected_profit_pct']:.1f}%)</td>
                    <td><span class="badge" style="background:#713f12;color:#fde047;">🟡 Esperando Venta</span></td>
                </tr>"""
            open_pos_html = f"""<div class="table-container" style="border: 1px solid #eab308; margin-bottom: 24px;">
                <div class="table-title" style="color:#fde047;">📦 POSICIONES / OPERACIONES ABIERTAS EN ESTE INSTANTE ({len(open_pos)})</div>
                <table>
                    <thead>
                        <tr>
                            <th>Cripto</th>
                            <th>Mercado</th>
                            <th>Dinero Invertido</th>
                            <th>Acciones</th>
                            <th>Precio Compra</th>
                            <th>Venta Objetivo</th>
                            <th>Ganancia Esperada</th>
                            <th>Estado</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                </table>
            </div>"""
        else:
            open_pos_html = """<div class="card" style="margin-bottom: 24px; border-left: 4px solid #3b82f6;">
                <div class="card-label" style="color:#93c5fd;">📦 Posiciones Abiertas</div>
                <div style="color:#94a3b8; font-size: 14px; margin-top: 4px;">
                    ⚪ Sin operaciones abiertas en este momento (100% de tu billetera libre y lista para cotizar).
                </div>
            </div>"""

        # 3. Filas de Oportunidades Encontradas
        market_rows = ""
        evals = diag.get("market_evals", [])
        for ev in evals[:10]:
            fair = ev["fair_price"]
            bid = ev["our_bid"]
            ask = ev["our_ask"]
            spread = ev["spread_captured"]
            m_type = ev["mispricing_type"]

            if m_type == "CHEAP_ASK":
                badge = '<span class="badge" style="background:#065f46;color:#a7f3d0;">🟢 COMPRA BARATA</span>'
            elif m_type == "EXPENSIVE_BID":
                badge = '<span class="badge" style="background:#991b1b;color:#fecaca;">🔴 VENTA CARA</span>'
            else:
                badge = '<span class="badge" style="background:#1e1b4b;color:#38bdf8;">⚡ SPREAD MAKER</span>'

            market_rows += f"""<tr>
                <td><span class="badge" style="background:#312e81;color:#c7d2fe;">{ev.get('asset', 'CRYPTO')}</span></td>
                <td><strong>{ev['question'][:60]}...</strong></td>
                <td style="color:#38bdf8;font-weight:600;">${fair:.3f}</td>
                <td style="color:#10b981;font-weight:700;">${bid:.3f}</td>
                <td style="color:#f87171;font-weight:700;">${ask:.3f}</td>
                <td style="color:#fbbf24;font-weight:700;">+{spread*100:.1f}¢</td>
                <td>{badge}</td>
            </tr>"""

        if not market_rows:
            market_rows = "<tr><td colspan='7' style='text-align:center;'>Analizando y sincronizando libros en vivo...</td></tr>"

        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Polymarket Quantitative Market Maker</title>
    <meta http-equiv="refresh" content="5">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 14px; border-bottom: 1px solid #1e293b; }}
        .title {{ font-size: 22px; font-weight: 700; display: flex; align-items: center; gap: 8px; color: #38bdf8; }}
        .badge {{ padding: 4px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 20px; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 16px; border: 1px solid #334155; }}
        .card-label {{ font-size: 11px; font-weight: 600; color: #94a3b8; text-transform: uppercase; margin-bottom: 6px; }}
        .card-value {{ font-size: 22px; font-weight: 700; color: #f8fafc; }}
        .card-sub {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
        .verdict-box {{ background: #1e293b; border-left: 4px solid #10b981; padding: 14px 18px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; }}
        .table-container {{ background: #1e293b; border-radius: 12px; padding: 16px; border: 1px solid #334155; overflow-x: auto; margin-bottom: 20px; }}
        .table-title {{ font-size: 13px; font-weight: 700; color: #94a3b8; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.05em; }}
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
                <span>🏛️</span> Polymarket Market Maker
            </div>
            <div>
                <span class="badge" style="background:#0369a1;color:#e0f2fe;"><span class="status-dot"></span>{'MODO DEMO (100% DATOS REALES)' if config.simulation_mode else 'MODO REAL'}</span>
            </div>
        </div>

        <!-- 1. RESUMEN DE BILLETERA -->
        <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));">
            <div class="card" style="border-top: 3px solid #38bdf8;">
                <div class="card-label">🏦 Balance Actual</div>
                <div class="card-value" style="color: #38bdf8;">${self.trader.balance_usdc:,.2f} USDC</div>
                <div class="card-sub">Inicial: ${self.trader.initial_balance:,.2f} USDC</div>
            </div>
            <div class="card" style="border-top: 3px solid #10b981;">
                <div class="card-label">📈 PnL de Spread Acumulado</div>
                <div class="card-value" style="color: {pnl_color};">{pnl:+,.2f} USDC</div>
                <div class="card-sub">WinRate: {winrate:.1f}% ({self.trader.wins_count}W / {self.trader.losses_count}L)</div>
            </div>
            <div class="card" style="border-top: 3px solid #f59e0b;">
                <div class="card-label">⚡ Estrategia y Mercados</div>
                <div class="card-value" style="font-size: 17px; color: #fbbf24;">100% MAKER</div>
                <div class="card-sub">Analizando {len(self.polymarket.active_markets)} libros en vivo</div>
            </div>
        </div>

        <!-- 2. DIAGNÓSTICO EN VIVO -->
        <div class="verdict-box">
            <strong>🔍 Análisis en Tiempo Real:</strong> {diag['verdict']}
        </div>

        <!-- 3. POSICIONES ABIERTAS -->
        {open_pos_html}

        <!-- 4. RADAR DE OPORTUNIDADES ENCONTRADAS -->
        <div class="table-container">
            <div class="table-title">🎯 RADAR DE OPORTUNIDADES Y ANÁLISIS EN VIVO ({len(self.polymarket.active_markets)} MERCADOS)</div>
            <table>
                <thead>
                    <tr>
                        <th>Cripto</th>
                        <th>Mercado Analizado</th>
                        <th>Precio Justo</th>
                        <th>Límite Compra</th>
                        <th>Límite Venta</th>
                        <th>Margen Spread</th>
                        <th>Oportunidad</th>
                    </tr>
                </thead>
                <tbody>
                    {market_rows}
                </tbody>
            </table>
        </div>

        <!-- 5. PRECIOS CRIPTO SPOT -->
        <div class="table-title" style="margin-top: 24px;">📈 PRECIOS SPOT DE EXCHANGES (COINBASE + KRAKEN + BINANCE)</div>
        <div class="grid">
            {crypto_cards}
        </div>
        
        <p style="text-align: center; color: #475569; font-size: 11px; margin-top: 20px;">
            Auto-refresco cada 5s • Rol: 100% MAKER • Sin Comisiones • Datos en Vivo de Polymarket CLOB
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
