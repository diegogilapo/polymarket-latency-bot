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
    Panel visual detallado, limpio y compacto.
    Diseñado para no truncar números en consolas estrechas.
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
                await asyncio.sleep(5)  # Actualización cada 5 segundos
            except Exception as e:
                console.print(f"[dim red]Error en dashboard: {e}[/dim red]")
                await asyncio.sleep(4)

    async def stop(self):
        self._running = False

    def _render(self):
        diag = self.detector.get_scan_diagnosis()
        
        # 1. TABLA PRINCIPAL DE EXCHANGES Y ESTADO
        table_main = Table(title="🚀 Polymarket Latency Bot - Monitor Multi-Exchange", border_style="cyan", show_header=True)
        table_main.add_column("Exchange", style="bold white", no_wrap=True)
        table_main.add_column("Precio BTC", style="bright_yellow", no_wrap=True)
        table_main.add_column("Estado de Conexión", style="dim white")

        now = time.time()
        for exch, price in self.price_feed.prices.items():
            last_t = self.price_feed.last_update_times.get(exch, 0)
            is_live = (now - last_t) < 15.0 and price > 0
            status_text = "[green]🟢 En vivo (Streaming)[/green]" if is_live else "[yellow]⏳ Sincronizando...[/yellow]"
            price_text = f"${price:,.2f}" if price > 0 else "---"
            table_main.add_row(exch, price_text, status_text)

        b_price = diag["btc_price"]
        b_delta = diag["btc_delta_5s"]
        b_vel = diag["btc_velocity"]
        delta_color = "[green]" if b_delta >= 0 else "[red]"

        table_main.add_row(
            "[bold cyan]BTC Consenso[/bold cyan]",
            f"[bold yellow]${b_price:,.2f}[/bold yellow]",
            f"Δ5s: {delta_color}{b_delta:+,.2f} USD[/] | Vel: {delta_color}{b_vel:+.1f} $/s[/]"
        )

        console.print(table_main)

        # 2. TABLA DE MERCADOS POLYMARKET Y DESFASES
        table_markets = Table(title="🎯 Mercados Polymarket & Análisis de Desfase", border_style="magenta", show_header=True)
        table_markets.add_column("Mercado", style="bold white")
        table_markets.add_column("Bid", style="dim white", no_wrap=True)
        table_markets.add_column("Ask", style="bright_white", no_wrap=True)
        table_markets.add_column("Fair", style="bright_cyan", no_wrap=True)
        table_markets.add_column("Desfase", style="bright_yellow", no_wrap=True)
        table_markets.add_column("Señal", no_wrap=True)

        evals = diag.get("market_evals", [])
        if evals:
            for ev in evals[:5]:
                diff = ev["diff"]
                diff_str = f"+{diff*100:.1f}¢" if diff > 0 else f"{diff*100:.1f}¢"
                signal_tag = "[bold green]🟢 ENTRAR[/bold green]" if ev["is_signal"] else "[dim white]⚪ Esperar[/dim white]"
                table_markets.add_row(
                    f"{ev['question'][:36]} ({ev['outcome']})",
                    f"{ev['best_bid']:.3f}",
                    f"{ev['best_ask']:.3f}",
                    f"{ev['fair_value']:.3f}",
                    diff_str,
                    signal_tag
                )
        else:
            table_markets.add_row("Sincronizando libros...", "---", "---", "---", "---", "---")

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
        console.print(Panel(diag_msg, title="🔍 Diagnóstico de Señal", border_style="yellow"))
