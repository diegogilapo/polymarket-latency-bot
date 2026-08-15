import asyncio
import time
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from src.config import config
from src.feeds.binance_feed import BinanceFeed
from src.feeds.coinbase_feed import CoinbaseFeed
from src.feeds.polymarket_feed import PolymarketFeed
from src.engine.paper_trader import PaperTradingEngine
from src.utils.logger import console

class Dashboard:
    """
    Panel visual en tiempo real para monitorear el estado del bot, precios y balance.
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
        self._running: bool = False

    async def start(self):
        self._running = True
        # Esperar 5s a que los feeds se conecten
        await asyncio.sleep(5)
        
        while self._running:
            try:
                self._render()
                await asyncio.sleep(6)  # Actualización cada 6 segundos
            except Exception as e:
                console.print(f"[dim red]Error en dashboard: {e}[/dim red]")
                await asyncio.sleep(5)

    async def stop(self):
        self._running = False

    def _render(self):
        table = Table(title="🚀 Polymarket Latency Arbitrage Bot - Status Monitor", border_style="cyan", show_header=True)
        table.add_column("Métrica / Feed", style="bold white", width=26)
        table.add_column("Valor Actual", style="bright_yellow", width=22)
        table.add_column("Detalles / Estado", style="dim white")

        # Precios BTC
        b_price = self.binance.current_price
        b_delta = self.binance.get_price_delta(config.btc_momentum_window_seconds)
        b_vel = self.binance.get_velocity()
        c_price = self.coinbase.current_price
        source_name = self.binance.active_source

        delta_color = "[green]" if b_delta >= 0 else "[red]"
        table.add_row(
            f"BTC Lead ({source_name})",
            f"${b_price:,.2f}",
            f"Δ5s: {delta_color}{b_delta:+,.2f} USD[/] | Vel: {delta_color}{b_vel:+.1f} $/s[/]"
        )
        table.add_row(
            "BTC Coinbase (Spot US)",
            f"${c_price:,.2f}" if c_price > 0 else "Conectando...",
            "Feed Directo EE.UU."
        )

        # Polymarket Feeds
        market_count = len(self.polymarket.active_markets)
        table.add_row(
            "Mercados Polymarket",
            f"{market_count} activos",
            f"Libros sincronizados por WS + REST"
        )

        # Paper Trading Metrics
        winrate = (self.trader.wins_count / self.trader.closed_trades_count * 100) if self.trader.closed_trades_count > 0 else 0.0
        pnl = self.trader.total_pnl_usdc
        pnl_color = "[bold green]" if pnl >= 0 else "[bold red]"
        
        table.add_row(
            "Modo de Operación",
            "DEMO (Paper Trading)" if config.simulation_mode else "[bold red]REAL MONEY[/bold red]",
            f"Latencia Simulada: {config.simulated_network_latency_ms}ms"
        )
        table.add_row(
            "Balance Virtual",
            f"${self.trader.balance_usdc:,.2f} USDC",
            f"Inicial: ${self.trader.initial_balance:,.2f} USDC"
        )
        table.add_row(
            "PnL Acumulado",
            f"{pnl_color}{pnl:+,.2f} USDC[/]",
            f"Operaciones: {self.trader.closed_trades_count} (W: {self.trader.wins_count} | L: {self.trader.losses_count}) | WinRate: {winrate:.1f}%"
        )
        table.add_row(
            "Posiciones Abiertas",
            f"{len(self.trader.open_positions)} activas",
            f"TP: +{config.take_profit_delta*100:.0f}¢ | SL: -{config.stop_loss_delta*100:.0f}¢ | Timeout: {config.position_timeout_seconds}s"
        )

        console.print(table)
