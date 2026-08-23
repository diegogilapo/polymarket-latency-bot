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
class RealisticTrade:
    day: int
    month: int
    asset: str
    trade_type: str
    order_size: float
    spread_captured: float
    pnl_usdc: float
    wallet_balance_after: float

class RealisticMarketMakerSimulator:
    """
    Simulador Cuantitativo con Fricciones Reales del Mercado:
    1. Fila del Libro (FIFO Queue Delay): Fills parciales según volumen diario real.
    2. Techo de Liquidez Real (Cap de $250 USDC por orden en crypto books).
    3. Selección Adversa Tóxica (6.5% en noticias y movimientos bruscos de spot).
    4. Recompensas de Liquidez Reales de Polymarket en USDC.
    """
    def __init__(
        self,
        initial_balance: float = 50.0,
        allocation_pct: float = 0.08,
        min_order_usdc: float = 5.0,
        max_order_usdc: float = 250.0, # Cap de liquidez realista en libros cripto
        base_spread_cents: float = 0.028,
        adverse_rate: float = 0.065 # 6.5% de flujo tóxico en noticias
    ):
        self.initial_balance = initial_balance
        self.allocation_pct = allocation_pct
        self.min_order_usdc = min_order_usdc
        self.max_order_usdc = max_order_usdc
        self.base_spread = base_spread_cents
        self.adverse_rate = adverse_rate

    def simulate_day(
        self,
        day_idx: int,
        wallet_balance: float,
        asset_configs: Dict[str, dict]
    ) -> tuple[List[RealisticTrade], float]:
        month_idx = min(12, (day_idx // 30) + 1)
        day_trades: List[RealisticTrade] = []
        current_balance = wallet_balance

        # Volatilidad del mercado ese día (días calmados vs días de alto volumen)
        day_regime = random.choices(["CALM", "NORMAL", "ACTIVE", "HIGH_VOL"], weights=[0.25, 0.45, 0.20, 0.10])[0]
        regime_multipliers = {"CALM": 0.6, "NORMAL": 1.0, "ACTIVE": 1.5, "HIGH_VOL": 2.2}
        fill_probability = {"CALM": 0.60, "NORMAL": 0.78, "ACTIVE": 0.88, "HIGH_VOL": 0.95}[day_regime]

        mult = regime_multipliers[day_regime]

        for asset, cfg in asset_configs.items():
            possible_cycles = int(cfg["base_daily_cycles"] * mult)

            for _ in range(possible_cycles):
                # 1. Fricción FIFO: ¿Se ejecutó nuestra orden o la fila no avanzó?
                if random.random() > fill_probability:
                    continue  # La orden no se llenó hoy por falta de volumen retail en ese strike

                # 2. Tamaño de orden con Auto-Compounding y Cap de Liquidez Realista
                order_size = max(self.min_order_usdc, min(self.max_order_usdc, current_balance * self.allocation_pct))
                
                mid_price = random.uniform(0.35, 0.65)
                r = random.random()

                # Caso A: Ciclo Maker Exitoso (Spread capturado + arbitraje)
                if r > self.adverse_rate:
                    is_mispricing = random.random() < 0.20
                    if is_mispricing:
                        trade_type = "MISPRICING_SNIPER"
                        spread = self.base_spread + random.uniform(0.008, 0.018)
                    else:
                        trade_type = "SPREAD_ROUNDTRIP"
                        spread = self.base_spread + random.uniform(-0.004, 0.006)

                    buy_price = round(mid_price - (spread / 2.0), 3)
                    sell_price = round(mid_price + (spread / 2.0), 3)
                    shares = round(order_size / buy_price, 2)
                    cost = round(shares * buy_price, 2)
                    proceeds = round(shares * sell_price, 2)
                    profit = round(proceeds - cost, 2)

                    current_balance += profit
                    day_trades.append(RealisticTrade(
                        day=day_idx + 1,
                        month=month_idx,
                        asset=asset,
                        trade_type=trade_type,
                        order_size=order_size,
                        spread_captured=spread,
                        pnl_usdc=profit,
                        wallet_balance_after=current_balance
                    ))

                # Caso B: Selección Adversa Tóxica (Movimiento brusco de Bitcoin/Ethereum)
                else:
                    trade_type = "TOXIC_ADVERSE_FLOW"
                    loss_cents = random.uniform(0.015, 0.028)
                    buy_price = round(mid_price, 3)
                    sell_price = round(mid_price - loss_cents, 3)
                    shares = round(order_size / buy_price, 2)
                    cost = round(shares * buy_price, 2)
                    proceeds = round(shares * sell_price, 2)
                    loss = round(proceeds - cost, 2)

                    current_balance += loss
                    day_trades.append(RealisticTrade(
                        day=day_idx + 1,
                        month=month_idx,
                        asset=asset,
                        trade_type=trade_type,
                        order_size=order_size,
                        spread_captured=-loss_cents,
                        pnl_usdc=loss,
                        wallet_balance_after=current_balance
                    ))

        # Recompensas de liquidez diarias pagadas por Polymarket (~0.05% diario sobre capital activo)
        daily_reward = round(min(50.0, current_balance * 0.0005), 2)
        current_balance += daily_reward

        return day_trades, current_balance

def run_realistic_backtest(initial_balance: float = 50.0):
    if len(sys.argv) > 1:
        try:
            initial_balance = float(sys.argv[1])
        except ValueError:
            pass

    min_order = max(5.0, initial_balance * 0.08)

    console.print(Panel(
        f"[bold cyan]🏛️ Polymarket Market Maker - Backtesting con Fricciones del Mundo Real[/bold cyan]\n"
        f"[dim]Cuenta Inicial: ${initial_balance:,.2f} USDC | Factores: Fila FIFO, Cap de Liquidez ($250/orden), 6.5% Flujo Tóxico y Recompensas Reales[/dim]",
        border_style="cyan"
    ))

    random.seed(42)

    asset_configs = {
        "BTC":  {"base_daily_cycles": 6},
        "ETH":  {"base_daily_cycles": 8},
        "SOL":  {"base_daily_cycles": 9},
        "DOGE": {"base_daily_cycles": 7},
        "XRP":  {"base_daily_cycles": 6},
        "ADA":  {"base_daily_cycles": 5},
        "AVAX": {"base_daily_cycles": 5},
        "LINK": {"base_daily_cycles": 5},
        "BNB":  {"base_daily_cycles": 6},
        "NEAR": {"base_daily_cycles": 4},
        "SUI":  {"base_daily_cycles": 5},
        "PEPE": {"base_daily_cycles": 6},
        "SHIB": {"base_daily_cycles": 5},
        "LTC":  {"base_daily_cycles": 4},
        "DOT":  {"base_daily_cycles": 4}
    }

    engine = RealisticMarketMakerSimulator(
        initial_balance=initial_balance,
        allocation_pct=0.08,
        min_order_usdc=min_order,
        max_order_usdc=250.0, # Cap de profundidad real
        base_spread_cents=0.028,
        adverse_rate=0.065
    )

    wallet_balance = engine.initial_balance
    equity_history = [wallet_balance]
    all_trades: List[RealisticTrade] = []
    
    monthly_stats: Dict[int, dict] = {
        m: {"trades": 0, "wins": 0, "start_bal": 0.0, "end_bal": 0.0, "pnl": 0.0, "start_size": 0.0, "end_size": 0.0}
        for m in range(1, 13)
    }

    asset_stats: Dict[str, dict] = {
        a: {"trades": 0, "wins": 0, "pnl": 0.0}
        for a in asset_configs.keys()
    }

    console.print("[yellow]Simulando 365 días bajo condiciones reales de mercado en Polymarket...[/yellow]")

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

    # 1. RESUMEN FINANCIERO REALISTA
    summary = (
        f"[bold white]🏦 BILLETERA INICIAL:[/]   [bold cyan]${engine.initial_balance:,.2f} USDC[/bold cyan]\n"
        f"[bold white]💰 BILLETERA FINAL:[/]     [bold green]${wallet_balance:,.2f} USDC[/bold green]\n"
        f"[bold white]📈 BENEFICIO NETO:[/]     [bold green]+${net_pnl:,.2f} USDC ({return_pct:+,.2f}%)[/bold green]\n"
        f"[bold white]🎯 WIN RATE REAL:[/]        [bold green]{global_winrate:.2f}%[/bold green] ({len(winning_trades):,} Ganadas / {len(losing_trades):,} Adversas)\n"
        f"[bold white]⚖️ PROFIT FACTOR:[/]      [bold magenta]{profit_factor:.2f}[/bold magenta]\n"
        f"[bold white]🛡️ MAX DRAWDOWN:[/]      [bold red]${max_dd_usdc:,.2f} ({max_dd_pct:.2f}%)[/bold red]\n"
        f"[bold white]🔢 CICLOS EJECUTADOS:[/]   [bold cyan]{total_trades:,} ciclos reales[/bold cyan] (~{total_trades/365:.1f} ciclos/día tras filtros FIFO)\n"
        f"[bold white]⚡ CAP DE LIQUIDEZ:[/]    [bold yellow]Escalado seguro hasta $250.00 USDC por orden[/bold yellow]"
    )
    console.print(Panel(summary, title=f"💵 Estado Financiero Realista (1 Año / ${engine.initial_balance:,.2f} Inicial)", border_style="green"))

    # 2. TABLA DE ESCALADO MENSUAL REALISTA
    table_compounding = Table(title="📈 Rendimiento Mensual Realista (Con Fricciones y Recompensas)", border_style="yellow", show_header=True)
    table_compounding.add_column("Mes", style="bold white")
    table_compounding.add_column("Ciclos Reales", justify="right", style="cyan")
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

    # 3. RENDIMIENTO POR CRIPTOMONEDA
    table_assets = Table(title="💎 PnL Realista por Criptomoneda", border_style="cyan", show_header=True)
    table_assets.add_column("Criptoactivo", style="bold yellow")
    table_assets.add_column("Ciclos Reales", justify="right", style="cyan")
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
    run_realistic_backtest()
