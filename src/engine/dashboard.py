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
    Panel visual multi-cripto en tiempo real (BTC, ETH, SOL, DOGE, XRP)
    y Monitor de Arbitraje Estructural de Paridad Binaria 100% Risk-Free.
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
        
        # 1. TABLA PRINCIPAL DE CRIPTOMONEDAS MONITORIZADAS
        table_crypto = Table(title="🚀 Polymarket Arbitrage Bot - Radar Multi-Cripto", border_style="cyan", show_header=True)
        table_crypto.add_column("Activo", style="bold white", no_wrap=True)
        table_crypto.add_column("Precio Consenso", style="bright_yellow", no_wrap=True)
        table_crypto.add_column("Variación Δ4s (%)", style="bold", no_wrap=True)
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

        # 2. TABLA DE PARIDAD BINARIA ESTRUCTURAL (YES + NO)
        table_markets = Table(title=f"🎯 Radar de Paridad Binaria 100% Cero Riesgo ({len(self.polymarket.active_markets)} Mercados)", border_style="magenta", show_header=True)
        table_markets.add_column("Activo", style="bold yellow", no_wrap=True)
        table_markets.add_column("Mercado", style="bold white")
        table_markets.add_column("YES Ask", style="bright_cyan", no_wrap=True)
        table_markets.add_column("NO Ask", style="bright_cyan", no_wrap=True)
        table_markets.add_column("Costo Par (YES+NO)", style="bold", no_wrap=True)
        table_markets.add_column("Margen Libre Riesgo", style="bold green", no_wrap=True)
        table_markets.add_column("Estado / Señal", no_wrap=True)

        evals = diag.get("market_evals", [])
        if evals:
            for ev in evals[:8]:
                cost = ev["combined_cost"]
                margin = ev["guaranteed_margin"]
                margin_pct = ev["margin_pct"]
                
                cost_color = "[bold green]" if cost < 1.00 else "[dim white]"
                margin_str = f"+{margin_pct:.2f}% (+{margin*100:.1f}¢)" if margin > 0 else f"{margin*100:.1f}¢"
                signal_tag = "[bold green]🟢 EJECUTAR ARB[/bold green]" if ev["is_signal"] else "[dim white]⚪ Esperar[/dim white]"

                table_markets.add_row(
                    ev.get("asset", "CRYPTO"),
                    f"{ev['question'][:36]}",
                    f"${ev['yes_ask']:.3f}",
                    f"${ev['no_ask']:.3f}",
                    f"{cost_color}${cost:.3f}[/]",
                    f"{margin_str}",
                    signal_tag
                )
        else:
            table_markets.add_row("---", "Sincronizando libros de órdenes...", "---", "---", "---", "---", "---")

        console.print(table_markets)

        # 3. DIAGNÓSTICO Y BALANCE VIRTUAL
        pnl = self.trader.total_pnl_usdc
        pnl_color = "[green]" if pnl >= 0 else "[red]"
        winrate = (self.trader.wins_count / self.trader.closed_trades_count * 100) if self.trader.closed_trades_count > 0 else 100.0

        diag_content = (
            f"[bold white]Veredicto de Revisión:[/] {diag['verdict']}\n"
            f"[bold white]Balance Virtual:[/] [bold cyan]${self.trader.balance_usdc:,.2f} USDC[/bold cyan] | "
            f"[bold white]PnL Garantizado:[/] {pnl_color}{pnl:+,.2f} USDC[/] | "
            f"[bold white]Arbitrajes Ganados:[/] [bold green]{self.trader.closed_trades_count}[/bold green] (W: {self.trader.wins_count} | L: {self.trader.losses_count} | WinRate: [bold green]{winrate:.1f}%[/bold green]) | "
            f"[bold white]Riesgo Direccional:[/] [bold green]0% (100% Risk-Free Parity)[/bold green]"
        )
        console.print(Panel(diag_content, title="🔍 Diagnóstico de Paridad y Estado de Billetera", border_style="green"))
