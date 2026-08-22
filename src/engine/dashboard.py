import asyncio
import time
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from src.config import config
from src.feeds.multi_feed import MultiExchangePriceFeed
from src.feeds.polymarket_feed import PolymarketFeed
from src.engine.paper_trader import PaperTradingEngine
from src.engine.arbitrage_detector import ArbitrageDetector
from src.utils.logger import console

class Dashboard:
    """
    Panel visual en tiempo real para el Motor de Market Making Cuantitativo con Órdenes Límite.
    Muestra precios spot de exchanges, cotizaciones óptimas de Bid/Ask y captura de spread.
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
        self._running: bool = False

    async def start(self):
        self._running = True
        await asyncio.sleep(3)
        
        while self._running:
            try:
                self._render()
                await asyncio.sleep(4)
            except Exception as e:
                console.print(f"[dim red]Error en dashboard: {e}[/dim red]")
                await asyncio.sleep(3)

    async def stop(self):
        self._running = False

    def _render(self):
        diag = self.detector.get_scan_diagnosis()
        
        # 1. TABLA PRINCIPAL DE CRIPTOMONEDAS
        table_crypto = Table(title="🚀 Polymarket Quantitative Market Maker - Radar Spot", border_style="cyan", show_header=True)
        table_crypto.add_column("Activo", style="bold white", no_wrap=True)
        table_crypto.add_column("Precio Consenso", style="bright_yellow", no_wrap=True)
        table_crypto.add_column("Variación Δ3s (%)", style="bold", no_wrap=True)
        table_crypto.add_column("Feeds Conectados", style="green", no_wrap=True)

        for asset in config.monitored_assets:
            p = self.price_feed.get_price(asset)
            pct = self.price_feed.get_pct_delta(asset, config.momentum_window_seconds) * 100.0
            pct_color = "[green]" if pct >= 0 else "[red]"
            
            active_exchs = [
                exch for exch, pr in self.price_feed.asset_prices.get(asset, {}).items()
                if pr > 0
            ]
            exchs_str = ", ".join(active_exchs) if active_exchs else "Sincronizando..."
            p_str = f"${p:,.4f}" if p < 1.0 else f"${p:,.2f}"

            table_crypto.add_row(
                f"[bold cyan]{asset}[/bold cyan]",
                p_str if p > 0 else "---",
                f"{pct_color}{pct:+.2f}%[/]",
                exchs_str
            )

        console.print(table_crypto)

        # 2. TABLA DE COTIZACIÓN LÍMITE Y MARKET MAKING
        table_markets = Table(title=f"🎯 Cotización Límite y Captura de Spread ({len(self.polymarket.active_markets)} Mercados)", border_style="magenta", show_header=True)
        table_markets.add_column("Activo", style="bold yellow", no_wrap=True)
        table_markets.add_column("Mercado", style="bold white")
        table_markets.add_column("Fair Value", style="bright_cyan", no_wrap=True)
        table_markets.add_column("Límite Compra (Bid)", style="green", no_wrap=True)
        table_markets.add_column("Límite Venta (Ask)", style="bright_red", no_wrap=True)
        table_markets.add_column("Spread Capturado", style="bold bright_yellow", no_wrap=True)
        table_markets.add_column("Inventario", style="dim white", no_wrap=True)
        table_markets.add_column("Oportunidad", no_wrap=True)

        evals = diag.get("market_evals", [])
        if evals:
            for ev in evals[:8]:
                fair = ev["fair_price"]
                bid = ev["our_bid"]
                ask = ev["our_ask"]
                spread = ev["spread_captured"]
                inv = ev["inventory"]
                m_type = ev["mispricing_type"]

                if m_type == "CHEAP_ASK":
                    opp_tag = "[bold green]🟢 COMPRA BARATA[/bold green]"
                elif m_type == "EXPENSIVE_BID":
                    opp_tag = "[bold red]🔴 VENTA CARA[/bold red]"
                else:
                    opp_tag = "[bright_cyan]⚡ SPREAD MAKER[/bright_cyan]"

                table_markets.add_row(
                    ev.get("asset", "CRYPTO"),
                    f"{ev['question'][:32]}",
                    f"${fair:.3f}",
                    f"${bid:.3f}",
                    f"${ask:.3f}",
                    f"+{spread*100:.1f}¢",
                    f"{inv:.0f} sh",
                    opp_tag
                )
        else:
            table_markets.add_row("---", "Sincronizando libros de órdenes...", "---", "---", "---", "---", "---", "---")

        console.print(table_markets)

        # 3. DIAGNÓSTICO Y BALANCE VIRTUAL
        pnl = self.trader.total_pnl_usdc
        pnl_color = "[green]" if pnl >= 0 else "[red]"
        winrate = (self.trader.wins_count / self.trader.closed_trades_count * 100) if self.trader.closed_trades_count > 0 else 100.0

        diag_content = (
            f"[bold white]Veredicto de Revisión:[/] {diag['verdict']}\n"
            f"[bold white]Balance Virtual:[/] [bold cyan]${self.trader.balance_usdc:,.2f} USDC[/bold cyan] | "
            f"[bold white]PnL de Spread Acumulado:[/] {pnl_color}{pnl:+,.2f} USDC[/] | "
            f"[bold white]Ciclos Completados:[/] [bold green]{self.trader.closed_trades_count}[/bold green] (W: {self.trader.wins_count} | L: {self.trader.losses_count} | WinRate: [bold green]{winrate:.1f}%[/bold green]) | "
            f"[bold white]Rol de Ejecución:[/] [bold green]100% MAKER (Cero Comisiones / Spread Cobrado)[/bold green]"
        )
        console.print(Panel(diag_content, title="🔍 Diagnóstico de Market Making y Estado de Billetera", border_style="green"))
