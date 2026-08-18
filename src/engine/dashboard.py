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
    Panel visual multi-cripto en tiempo real (BTC, ETH, SOL, DOGE, XRP).
    Muestra los precios de cada activo, mercados de Polymarket y diagnóstico de señal.
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
        await asyncio.sleep(4)
        
        while self._running:
            try:
                self._render()
                await asyncio.sleep(5)
            except Exception as e:
                console.print(f"[dim red]Error en dashboard: {e}[/dim red]")
                await asyncio.sleep(4)

    async def stop(self):
        self._running = False

    def _render(self):
        diag = self.detector.get_scan_diagnosis()
        
        # 1. TABLA PRINCIPAL DE CRIPTOMONEDAS MONITORIZADAS
        table_crypto = Table(title="🚀 Polymarket Latency Bot - Radar Multi-Cripto", border_style="cyan", show_header=True)
        table_crypto.add_column("Activo", style="bold white", no_wrap=True)
        table_crypto.add_column("Precio Consenso", style="bright_yellow", no_wrap=True)
        table_crypto.add_column("Variación Δ5s (%)", style="bold", no_wrap=True)
        table_crypto.add_column("Velocidad", style="dim white", no_wrap=True)
        table_crypto.add_column("Feeds Conectados", style="green", no_wrap=True)

        for asset in config.monitored_assets:
            p = self.price_feed.get_price(asset)
            pct = self.price_feed.get_pct_delta(asset, config.momentum_window_seconds) * 100.0
            vel = self.price_feed.get_velocity(asset)
            pct_color = "[green]" if pct >= 0 else "[red]"
            
            # Contar exchanges activos para este asset
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
                f"{vel:+.2f} $/s",
                exchs_str
            )

        console.print(table_crypto)

        # 2. TABLA DE MERCADOS POLYMARKET Y DESFASES
        table_markets = Table(title=f"🎯 Mercados Polymarket ({len(self.polymarket.active_markets)} Activos)", border_style="magenta", show_header=True)
        table_markets.add_column("Activo", style="bold yellow", no_wrap=True)
        table_markets.add_column("Mercado", style="bold white")
        table_markets.add_column("Bid", style="dim white", no_wrap=True)
        table_markets.add_column("Ask", style="bright_white", no_wrap=True)
        table_markets.add_column("Fair", style="bright_cyan", no_wrap=True)
        table_markets.add_column("Desfase", style="bright_yellow", no_wrap=True)
        table_markets.add_column("Señal", no_wrap=True)

        evals = diag.get("market_evals", [])
        valid_evals = [ev for ev in evals if ev.get("is_valid_book")]
        if not valid_evals:
            valid_evals = evals

        valid_evals.sort(key=lambda x: -x["diff"])

        if valid_evals:
            for ev in valid_evals[:8]:
                diff = ev["diff"]
                diff_str = f"+{diff*100:.1f}¢" if diff > 0 else f"{diff*100:.1f}¢"
                signal_tag = "[bold green]🟢 ENTRAR[/bold green]" if ev["is_signal"] else "[dim white]⚪ Esperar[/dim white]"
                table_markets.add_row(
                    ev.get("asset", "CRYPTO"),
                    f"{ev['question'][:32]} ({ev['outcome']})",
                    f"{ev['best_bid']:.3f}",
                    f"{ev['best_ask']:.3f}",
                    f"{ev['fair_value']:.3f}",
                    diff_str,
                    signal_tag
                )
        else:
            table_markets.add_row("---", "Sincronizando libros de órdenes...", "---", "---", "---", "---", "---")

        console.print(table_markets)

        # 3. PANEL DE DIAGNÓSTICO Y VEREDICTO DE ENTRADA
        winrate = (self.trader.wins_count / self.trader.closed_trades_count * 100) if self.trader.closed_trades_count > 0 else 0.0
        pnl = self.trader.total_pnl_usdc
        pnl_color = "[bold green]" if pnl >= 0 else "[bold red]"
        
        diag_msg = (
            f"[bold]Veredicto de Revisión:[/] {diag['verdict']}\n"
            f"[dim]Balance Virtual: ${self.trader.balance_usdc:,.2f} USDC | PnL Acumulado: {pnl_color}{pnl:+,.2f} USDC[/] | "
            f"Trades: {self.trader.closed_trades_count} (W: {self.trader.wins_count} | L: {self.trader.losses_count} | WinRate: {winrate:.1f}%) | "
            f"Posiciones Abiertas: {len(self.trader.open_positions)}[/dim]"
        )
        console.print(Panel(diag_msg, title="🔍 Diagnóstico de Señal Multi-Activo", border_style="yellow"))
