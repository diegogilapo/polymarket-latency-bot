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
    Panel Visual Intuitivo y Simplificado de Operaciones en Tiempo Real.
    Muestra de forma clara:
    1. Billetera y Rendimiento Financiero.
    2. Operaciones Abiertas (Dinero invertido, acciones y ganancia objetivo).
    3. Análisis del Mercado y Oportunidades Encontradas.
    4. Precios Spot de Criptomonedas en Vivo.
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
        await asyncio.sleep(2)
        
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
        
        # 1. PANEL DE BILLETERA Y ESTADO FINANCIERO (CLARO Y DESTACADO)
        pnl = self.trader.total_pnl_usdc
        pnl_color = "[green]" if pnl >= 0 else "[red]"
        winrate = (self.trader.wins_count / self.trader.closed_trades_count * 100) if self.trader.closed_trades_count > 0 else 100.0
        
        total_invested = getattr(self.trader, "total_positions_val", 0.0) or sum(i.shares_held * i.avg_buy_price for i in getattr(self.trader, "inventories", {}).values())
        total_equity = self.trader.balance_usdc + total_invested
        free_cash = getattr(self.trader, "free_cash", self.trader.balance_usdc)
        in_book_orders = getattr(self.trader, "active_orders_amount", 0.0)
        open_orders_cnt = len(getattr(self.trader, "open_orders", []))
        pos_cnt = len([i for i in getattr(self.trader, "inventories", {}).values() if i.shares_held >= 1.0])
        
        wallet_box = (
            f"[bold white]🏦 Cartera Total:[/] [bold cyan]${total_equity:,.2f} USDC[/bold cyan]  │  "
            f"[bold white]Disponible / Libre:[/] [bold green]${free_cash:,.2f} USDC[/bold green]  │  "
            f"[bold white]En Posiciones Abiertas:[/] [bold yellow]${total_invested:,.2f} USDC ({pos_cnt} mercados)[/bold yellow]  │  "
            f"[bold white]PnL:[/] {pnl_color}{pnl:+,.2f} USDC[/]  │  "
            f"[bold white]WinRate:[/] [bold green]{winrate:.1f}%[/bold green]\n"
            f"[bold white]⚡ Estrategia:[/] [bold green]Market Making Cuantitativo (Maker-Only / Cobrando Spread)[/bold green]  │  "
            f"[bold white]Mercados Analizados:[/] [bold yellow]{len(self.polymarket.active_markets)} libros en vivo[/bold yellow]"
        )
        console.print(Panel(wallet_box, title="💵 ESTADO DE BILLETERA Y RENDIMIENTO", border_style="green"))

        # 2. PANEL DE OPERACIONES / POSICIONES ABIERTAS
        open_positions = self.trader.get_open_positions_summary()
        
        if open_positions:
            table_pos = Table(title="📦 POSICIONES / OPERACIONES ABIERTAS EN ESTE INSTANTE", border_style="yellow", show_header=True)
            table_pos.add_column("Cripto", style="bold yellow", no_wrap=True)
            table_pos.add_column("Mercado en Operación", style="bold white")
            table_pos.add_column("Dinero Invertido", justify="right", style="bold cyan", no_wrap=True)
            table_pos.add_column("Acciones", justify="right", style="dim white", no_wrap=True)
            table_pos.add_column("Precio Compra", justify="right", style="bright_cyan", no_wrap=True)
            table_pos.add_column("Venta Objetivo", justify="right", style="bright_yellow", no_wrap=True)
            table_pos.add_column("Ganancia Esperada", justify="right", style="bold green", no_wrap=True)
            table_pos.add_column("Estado", no_wrap=True)

            for pos in open_positions:
                table_pos.add_row(
                    f"[bold yellow]{pos['asset']}[/bold yellow]",
                    f"{pos['question'][:38]}...",
                    f"${pos['invested_usdc']:.2f} USDC",
                    f"{pos['shares_held']:.1f} sh",
                    f"${pos['avg_buy_price']:.3f}",
                    f"${pos['target_sell_price']:.3f}",
                    f"+${pos['projected_profit_usdc']:.2f} (+{pos['projected_profit_pct']:.1f}%)",
                    "[bold yellow]🟡 Esperando Venta[/bold yellow]"
                )
            console.print(table_pos)
        else:
            no_pos_text = (
                "[dim green]✅ Sin operaciones abiertas en este segundo (100% del capital líquido disponible para cotizar).[/dim green]"
            )
            console.print(Panel(no_pos_text, title="📦 POSICIONES / OPERACIONES ABIERTAS", border_style="blue"))

        # 3. PANEL DE ANÁLISIS DE MERCADO Y OPORTUNIDADES ENCONTRADAS
        table_opps = Table(title="🎯 RADAR DE OPORTUNIDADES Y ANÁLISIS DE MERCADO EN VIVO", border_style="cyan", show_header=True)
        table_opps.add_column("Cripto", style="bold cyan", no_wrap=True)
        table_opps.add_column("Mercado Analizado", style="bold white")
        table_opps.add_column("Precio Justo", justify="right", style="bright_cyan", no_wrap=True)
        table_opps.add_column("Límite Compra", justify="right", style="green", no_wrap=True)
        table_opps.add_column("Límite Venta", justify="right", style="bright_red", no_wrap=True)
        table_opps.add_column("Margen Spread", justify="right", style="bold bright_yellow", no_wrap=True)
        table_opps.add_column("Análisis / Oportunidad", no_wrap=True)

        evals = diag.get("market_evals", [])
        if evals:
            for ev in evals[:6]:
                fair = ev["fair_price"]
                bid = ev["our_bid"]
                ask = ev["our_ask"]
                spread = ev["spread_captured"]
                m_type = ev["mispricing_type"]

                if m_type == "CHEAP_ASK":
                    opp_tag = "[bold green]🟢 OPORTUNIDAD: COMPRA BARATA[/bold green]"
                elif m_type == "EXPENSIVE_BID":
                    opp_tag = "[bold red]🔴 OPORTUNIDAD: VENTA CARA[/bold red]"
                else:
                    opp_tag = "[bright_cyan]⚡ COTIZANDO SPREAD MAKER[/bright_cyan]"

                table_opps.add_row(
                    ev.get("asset", "CRYPTO"),
                    f"{ev['question'][:42]}...",
                    f"${fair:.3f}",
                    f"${bid:.3f}",
                    f"${ask:.3f}",
                    f"+{spread*100:.1f}¢",
                    opp_tag
                )
        else:
            table_opps.add_row("---", "Analizando y sincronizando libros...", "---", "---", "---", "---", "---")

        console.print(table_opps)

        # 4. PRECIOS SPOT DE CRIPTOMONEDAS EN VIVO (LÍNEA RESUMIDA Y LIMPIA)
        prices_summary = []
        for asset in config.monitored_assets:
            p = self.price_feed.get_price(asset)
            pct = self.price_feed.get_pct_delta(asset, config.momentum_window_seconds) * 100.0
            pct_col = "[green]" if pct >= 0 else "[red]"
            p_str = f"${p:,.4f}" if p < 1.0 else f"${p:,.2f}"
            prices_summary.append(f"[bold white]{asset}:[/] [yellow]{p_str if p > 0 else '---'}[/] ({pct_col}{pct:+.2f}%[/])")

        console.print(Panel("  •  ".join(prices_summary), title="📈 PRECIOS CRIPTO EN VIVO (Coinbase + Kraken + Binance)", border_style="dim white"))
        console.print("")
