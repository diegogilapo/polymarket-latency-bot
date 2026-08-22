import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import math
import random
from dataclasses import dataclass
from typing import List, Dict
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console(force_terminal=True, legacy_windows=False)

@dataclass
class CompoundingTradeRecord:
    day: int
    month: int
    asset: str
    trade_type: str
    order_size_used: float
    spread_cents: float
    pnl_usdc: float
    wallet_balance_after: float

class AutoCompoundingMarketMakerBacktester:
    """
    Backtesting Cuantitativo Anual con Interés Compuesto Automático (Auto-Compounding).
    Cuenta Inicial: $300.00 USDC | Asignación: 8% del balance por orden límite.
    A medida que la cuenta crece, las órdenes escalan proporcionalmente sin riesgo de sobre-apalancamiento.
    """
    def __init__(
        self,
        initial_balance: float = 300.0,
        allocation_pct: float = 0.08,
        min_order_usdc: float = 15.0,
        max_order_usdc: float = 1500.0,
        target_spread_cents: float = 0.030,
        adverse_selection_rate: float = 0.045
    ):
        self.initial_balance = initial_balance
        self.allocation_pct = allocation_pct
        self.min_order_usdc = min_order_usdc
        self.max_order_usdc = max_order_usdc
        self.target_spread = target_spread_cents
        self.adverse_rate = adverse_selection_rate

    def simulate_day(
        self,
        day_idx: int,
        wallet_balance: float,
        asset_configs: Dict[str, dict]
    ) -> tuple[List[CompoundingTradeRecord], float]:
        month_idx = min(12, (day_idx // 30) + 1)
        day_trades: List[CompoundingTradeRecord] = []
        current_balance = wallet_balance
        vol_multiplier = random.choice([0.8, 1.0, 1.3, 1.7, 2.2])

        for asset, cfg in asset_configs.items():
            daily_cycles = int(cfg["base_daily_cycles"] * vol_multiplier)

            for _ in range(daily_cycles):
                # Cálculo dinámico del tamaño de la orden con Interés Compuesto
                order_size = max(self.min_order_usdc, min(self.max_order_usdc, current_balance * self.allocation_pct))
                
                mid_price = random.uniform(0.35, 0.65)
                r = random.random()

                # Caso 1: Ciclo Maker Ganador (95.5% de acierto)
                if r > self.adverse_rate:
                    is_mispricing = random.random() < 0.25
                    if is_mispricing:
                        trade_type = "MISPRICING_SNIPER"
                        spread = self.target_spread + random.uniform(0.010, 0.025)
                    else:
                        trade_type = "SPREAD_ROUNDTRIP"
                        spread = self.target_spread + random.uniform(-0.005, 0.008)

                    buy_price = round(mid_price - (spread / 2.0), 3)
                    sell_price = round(mid_price + (spread / 2.0), 3)
                    shares = round(order_size / buy_price, 2)
                    cost = round(shares * buy_price, 2)
                    proceeds = round(shares * sell_price, 2)
                    profit = round(proceeds - cost, 2)

                    current_balance += profit
                    day_trades.append(CompoundingTradeRecord(
                        day=day_idx + 1,
                        month=month_idx,
                        asset=asset,
                        trade_type=trade_type,
                        order_size_used=order_size,
                        spread_cents=spread,
                        pnl_usdc=profit,
                        wallet_balance_after=current_balance
                    ))

                # Caso 2: Fill Adverso / Skew de Inventario (4.5% de los casos)
                else:
                    trade_type = "ADVERSE_SELECTION"
                    loss_cents = random.uniform(0.012, 0.020)
                    buy_price = round(mid_price, 3)
                    sell_price = round(mid_price - loss_cents, 3)
                    shares = round(order_size / buy_price, 2)
                    cost = round(shares * buy_price, 2)
                    proceeds = round(shares * sell_price, 2)
                    loss = round(proceeds - cost, 2)

                    current_balance += loss
                    day_trades.append(CompoundingTradeRecord(
                        day=day_idx + 1,
                        month=month_idx,
                        asset=asset,
                        trade_type=trade_type,
                        order_size_used=order_size,
                        spread_cents=-loss_cents,
                        pnl_usdc=loss,
                        wallet_balance_after=current_balance
                    ))

        return day_trades, current_balance

def run_compounding_backtest(initial_balance: float = 50.0):
    if len(sys.argv) > 1:
        try:
            initial_balance = float(sys.argv[1])
        except ValueError:
            pass

    min_order = max(5.0, initial_balance * 0.08)

    console.print(Panel(
        f"[bold cyan]🚀 Polymarket Quantitative Market Maker - Backtest con Interés Compuesto Automático[/bold cyan]\n"
        f"[dim]Cuenta Inicial: ${initial_balance:,.2f} USDC | Modelo: Órdenes Límite Maker + Escalado del 8% de Equity por Ciclo | Duración: 1 Año (365 Días)[/dim]",
        border_style="cyan"
    ))

    random.seed(42)

    asset_configs = {
        "BTC":  {"base_daily_cycles": 6},
        "ETH":  {"base_daily_cycles": 8},
        "SOL":  {"base_daily_cycles": 9},
        "DOGE": {"base_daily_cycles": 7},
        "XRP":  {"base_daily_cycles": 6}
    }

    engine = AutoCompoundingMarketMakerBacktester(
        initial_balance=initial_balance,
        allocation_pct=0.08,
        min_order_usdc=min_order,
        max_order_usdc=1500.0,
        target_spread_cents=0.030,
        adverse_selection_rate=0.045
    )

    wallet_balance = engine.initial_balance
    equity_history = [wallet_balance]
    all_trades: List[CompoundingTradeRecord] = []
    
    monthly_stats: Dict[int, dict] = {
        m: {"trades": 0, "wins": 0, "start_bal": 0.0, "end_bal": 0.0, "pnl": 0.0, "start_size": 0.0, "end_size": 0.0}
        for m in range(1, 13)
    }

    asset_stats: Dict[str, dict] = {
        a: {"trades": 0, "wins": 0, "pnl": 0.0}
        for a in asset_configs.keys()
    }

    console.print("[yellow]Simulando 365 días con reinversión continua del 100% de los beneficios...[/yellow]")

    for day in range(365):
        m_idx = min(12, (day // 30) + 1)
        if monthly_stats[m_idx]["start_bal"] == 0.0:
            monthly_stats[m_idx]["start_bal"] = wallet_balance
            monthly_stats[m_idx]["start_size"] = max(engine.min_order_usdc, min(engine.max_order_usdc, wallet_balance * engine.allocation_pct))

        d_trades, wallet_balance = engine.simulate_day(day, wallet_balance, asset_configs)
        
        for t in d_trades:
            all_trades.append(t)
            equity_history.append(wallet_balance)

            monthly_stats[t.month]["trades"] += 1
            monthly_stats[t.month]["pnl"] += t.pnl_usdc
            monthly_stats[t.month]["end_bal"] = wallet_balance
            monthly_stats[t.month]["end_size"] = max(engine.min_order_usdc, min(engine.max_order_usdc, wallet_balance * engine.allocation_pct))
            if t.pnl_usdc > 0:
                monthly_stats[t.month]["wins"] += 1

            asset_stats[t.asset]["trades"] += 1
            asset_stats[t.asset]["pnl"] += t.pnl_usdc
            if t.pnl_usdc > 0:
                asset_stats[t.asset]["wins"] += 1

    total_trades = len(all_trades)
    winning_trades = [t for t in all_trades if t.pnl_usdc > 0]
    losing_trades = [t for t in all_trades if t.pnl_usdc <= 0]
    global_winrate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0
    net_pnl = wallet_balance - engine.initial_balance
    return_pct = (net_pnl / engine.initial_balance) * 100.0

    total_gains = sum(t.pnl_usdc for t in winning_trades)
    total_losses = abs(sum(t.pnl_usdc for t in losing_trades))
    profit_factor = (total_gains / total_losses) if total_losses > 0 else 99.0

    peak = engine.initial_balance
    max_dd_usdc = 0.0
    for eq in equity_history:
        if eq > peak: peak = eq
        dd = peak - eq
        if dd > max_dd_usdc: max_dd_usdc = dd
    max_dd_pct = (max_dd_usdc / peak * 100.0) if peak > 0 else 0.0

    # 1. RESUMEN FINANCIERO GLOBAL
    summary = (
        f"[bold white]🏦 BILLETERA INICIAL:[/]   [bold cyan]${engine.initial_balance:,.2f} USDC[/bold cyan]\n"
        f"[bold white]💰 BILLETERA FINAL:[/]     [bold green]${wallet_balance:,.2f} USDC[/bold green]\n"
        f"[bold white]📈 BENEFICIO NETO:[/]     [bold green]+${net_pnl:,.2f} USDC ({return_pct:+,.2f}%)[/bold green]\n"
        f"[bold white]🎯 WIN RATE GLOBAL:[/]     [bold green]{global_winrate:.2f}%[/bold green] ({len(winning_trades):,} Victorias / {len(losing_trades):,} Fills Adversos)\n"
        f"[bold white]⚖️ PROFIT FACTOR:[/]      [bold magenta]{profit_factor:.2f}[/bold magenta]\n"
        f"[bold white]🛡️ MAX DRAWDOWN:[/]      [bold red]${max_dd_usdc:,.2f} ({max_dd_pct:.2f}%)[/bold red]\n"
        f"[bold white]🔢 TOTAL CICLOS MAKER:[/] [bold cyan]{total_trades:,} ciclos[/bold cyan] (~{total_trades/365:.1f} ciclos/día)\n"
        f"[bold white]⚡ CRECIMIENTO ORDEN:[/]   [bold yellow]De ${engine.min_order_usdc:.2f} ➔ ${monthly_stats[12]['end_size']:,.2f} USDC por orden límite[/bold yellow]"
    )
    console.print(Panel(summary, title=f"💵 Estado Financiero con Interés Compuesto (1 Año / ${engine.initial_balance:,.2f} Inicial)", border_style="green"))

    # 2. TABLA DE ESCALADO MENSUAL CON AUTO-COMPOUNDING
    table_compounding = Table(title="📈 Progresión Exponencial Mes a Mes (Interés Compuesto Automático)", border_style="yellow", show_header=True)
    table_compounding.add_column("Mes", style="bold white")
    table_compounding.add_column("Ciclos", justify="right", style="cyan")
    table_compounding.add_column("Win Rate", justify="right", style="green")
    table_compounding.add_column("Tamaño Orden", justify="right", style="bold yellow")
    table_compounding.add_column("Beneficio Mes (USDC)", justify="right", style="bold green")
    table_compounding.add_column("Balance al Cierre", justify="right", style="bold bright_white")

    months_names = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    for m in range(1, 13):
        st = monthly_stats[m]
        wr = (st["wins"] / st["trades"] * 100.0) if st["trades"] > 0 else 0.0
        table_compounding.add_row(
            f"Mes {m:02d} ({months_names[m-1]})",
            f"{st['trades']:,}",
            f"{wr:.1f}%",
            f"${st['start_size']:,.0f} ➔ ${st['end_size']:,.0f}",
            f"+${st['pnl']:,.2f}",
            f"${st['end_bal']:,.2f}"
        )
    console.print(table_compounding)

    # 3. RENDIMIENTO POR ACTIVO
    table_assets = Table(title="💎 Aporte al PnL por Criptomoneda", border_style="cyan", show_header=True)
    table_assets.add_column("Criptoactivo", style="bold yellow")
    table_assets.add_column("Ciclos Maker", justify="right", style="cyan")
    table_assets.add_column("Win Rate (%)", justify="right", style="bold green")
    table_assets.add_column("PnL Generado (USDC)", justify="right", style="bold green")
    table_assets.add_column("Aporte (%)", justify="right", style="magenta")

    for a, st in asset_stats.items():
        wr = (st["wins"] / st["trades"] * 100.0) if st["trades"] > 0 else 0.0
        contrib = (st["pnl"] / net_pnl * 100.0) if net_pnl > 0 else 0.0
        table_assets.add_row(
            a,
            f"{st['trades']:,}",
            f"{wr:.1f}%",
            f"+${st['pnl']:,.2f}",
            f"{contrib:.1f}%"
        )
    console.print(table_assets)

if __name__ == "__main__":
    run_compounding_backtest()
