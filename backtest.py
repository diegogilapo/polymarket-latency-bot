import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import time
import math
import random
from typing import List, Tuple
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from src.engine.backtester import PolymarketLatencyBacktester, BacktestResult

console = Console(force_terminal=True, legacy_windows=False)

def generate_hft_price_series(
    start_price: float = 63000.0,
    duration_hours: float = 24.0,
    interval_sec: float = 1.0,
    annual_vol: float = 0.65,
    jump_probability_per_min: float = 0.15,
    jump_std: float = 0.0022
) -> List[Tuple[float, float]]:
    """
    Genera 86,400 segundos de microestructura de alta frecuencia con saltos estocásticos de volatilidad.
    """
    total_steps = int(duration_hours * 3600 / interval_sec)
    dt = interval_sec / (365.0 * 24.0 * 3600.0)
    mu = 0.0
    sigma = annual_vol
    
    prices = [(0.0, start_price)]
    current_p = start_price
    
    random.seed(42)
    
    for step in range(1, total_steps):
        t = step * interval_sec
        z = random.gauss(0, 1)
        drift = (mu - 0.5 * sigma ** 2) * dt
        shock = sigma * math.sqrt(dt) * z
        ret = drift + shock
        
        # Micro-impulso de mercado / absorción de liquidez
        if random.random() < (jump_probability_per_min / 60.0):
            jump = random.gauss(0, jump_std)
            ret += jump
            
        current_p = current_p * math.exp(ret)
        prices.append((t, current_p))
        
    return prices

def run_backtests():
    console.print(Panel("[bold cyan]🚀 Polymarket Latency Bot - Suite Cuantitativa de Backtesting[/bold cyan]\n"
                        "[dim]Simulación de Microestructura de Mercado (24 Horas / 86,400 Ticks a 1s) en BTC, ETH y SOL[/dim]",
                        border_style="cyan"))

    console.print("[yellow]Generando 86,400 segundos de microestructura de mercado para BTC, ETH y SOL...[/yellow]")
    btc_ticks = generate_hft_price_series(start_price=63000.0, duration_hours=24.0, annual_vol=0.65, jump_std=0.0020)
    eth_ticks = generate_hft_price_series(start_price=2650.0, duration_hours=24.0, annual_vol=0.75, jump_std=0.0025)
    sol_ticks = generate_hft_price_series(start_price=145.0, duration_hours=24.0, annual_vol=0.90, jump_std=0.0035)

    # CASO 1: Configuración Antigua (Por qué dio 0 trades)
    old_backtester = PolymarketLatencyBacktester(
        initial_balance=1000.0,
        order_size_usdc=50.0,
        bot_latency_ms=15.0,
        mm_cancel_delay_ms=350.0,
        min_discrepancy=0.04,   # 4.0¢
        take_profit=0.08,
        stop_loss=0.06,
        timeout_sec=45.0,
        momentum_window_sec=5.0,
        fast_move_pct=0.0015
    )
    res_old = old_backtester.run_simulation(btc_ticks, asset="BTC", expiry_hours=8760.0, strike_offset_pct=0.50)

    # CASO 2: Nueva Estrategia Optimizada en BTC (Contratos Intradía / Near-The-Money + Black-Scholes Delta)
    opt_btc = PolymarketLatencyBacktester(
        initial_balance=1000.0,
        order_size_usdc=50.0,
        bot_latency_ms=15.0,      # Virginia (15ms)
        mm_cancel_delay_ms=380.0, # MM tarda ~380ms en cancelar
        min_discrepancy=0.020,    # 2.0¢
        take_profit=0.035,        # +3.5¢ scalp
        stop_loss=0.025,          # -2.5¢ SL
        timeout_sec=25.0,
        momentum_window_sec=5.0,
        fast_move_pct=0.0006      # 0.06% en 5s (~$38 en BTC)
    )
    res_opt_btc = opt_btc.run_simulation(btc_ticks, asset="BTC", expiry_hours=2.0, strike_offset_pct=0.001)

    # CASO 3: Nueva Estrategia Optimizada en ETH
    opt_eth = PolymarketLatencyBacktester(
        initial_balance=1000.0,
        order_size_usdc=50.0,
        bot_latency_ms=15.0,
        mm_cancel_delay_ms=450.0, # En ETH los MMs son más lentos
        min_discrepancy=0.020,
        take_profit=0.040,
        stop_loss=0.025,
        timeout_sec=25.0,
        momentum_window_sec=5.0,
        fast_move_pct=0.0007      # 0.07% en 5s (~$1.85 en ETH)
    )
    res_opt_eth = opt_eth.run_simulation(eth_ticks, asset="ETH", expiry_hours=2.0, strike_offset_pct=0.001)

    # CASO 4: Nueva Estrategia Optimizada en SOL (Mayor volatilidad = mayores desfases)
    opt_sol = PolymarketLatencyBacktester(
        initial_balance=1000.0,
        order_size_usdc=50.0,
        bot_latency_ms=15.0,
        mm_cancel_delay_ms=550.0, # En SOL los MMs son más lentos
        min_discrepancy=0.025,
        take_profit=0.045,
        stop_loss=0.030,
        timeout_sec=30.0,
        momentum_window_sec=5.0,
        fast_move_pct=0.0009      # 0.09% en 5s (~$0.13 en SOL)
    )
    res_opt_sol = opt_sol.run_simulation(sol_ticks, asset="SOL", expiry_hours=2.0, strike_offset_pct=0.002)

    # CASO 5: Portafolio Combinado Multi-Activo
    combined_trades = res_opt_btc.trades + res_opt_eth.trades + res_opt_sol.trades
    combined_trades.sort(key=lambda t: t.timestamp)
    combined_wins = [t for t in combined_trades if t.pnl_usdc > 0]
    combined_losses = [t for t in combined_trades if t.pnl_usdc <= 0]
    comb_total = len(combined_trades)
    comb_wr = (len(combined_wins) / comb_total * 100.0) if comb_total > 0 else 0.0
    comb_net = sum(t.pnl_usdc for t in combined_trades)
    comb_gains = sum(t.pnl_usdc for t in combined_wins)
    comb_losses = abs(sum(t.pnl_usdc for t in combined_losses))
    comb_pf = (comb_gains / comb_losses) if comb_losses > 0 else (99.0 if comb_gains > 0 else 0.0)

    # TABLA COMPARATIVA DE RESULTADOS
    table = Table(title="📊 Resultados Comparativos de Backtesting (24 Horas)", border_style="green", show_header=True)
    table.add_column("Estrategia / Configuración", style="bold white")
    table.add_column("Trades", justify="right", style="cyan")
    table.add_column("Win Rate (%)", justify="right", style="bold")
    table.add_column("PnL Neto (USDC)", justify="right", style="bold")
    table.add_column("Rentabilidad (%)", justify="right")
    table.add_column("Profit Factor", justify="right", style="magenta")
    table.add_column("Max Drawdown", justify="right", style="red")

    def format_row(name, res: BacktestResult):
        wr_color = "[green]" if res.win_rate >= 60 else ("[yellow]" if res.win_rate > 0 else "[dim white]")
        pnl_color = "[green]" if res.net_pnl_usdc > 0 else ("[red]" if res.net_pnl_usdc < 0 else "[dim white]")
        table.add_row(
            name,
            str(res.total_trades),
            f"{wr_color}{res.win_rate:.1f}%[/]",
            f"{pnl_color}${res.net_pnl_usdc:+,.2f}[/]",
            f"{pnl_color}{res.return_pct:+.2f}%[/]",
            f"{res.profit_factor:.2f}" if res.total_trades > 0 else "---",
            f"${res.max_drawdown_usdc:.2f} ({res.max_drawdown_pct:.1f}%)" if res.total_trades > 0 else "---"
        )

    format_row("Configuración Antigua (Macro / Largo Plazo)", res_old)
    format_row("Estrategia Optimizada: BTC Intradía", res_opt_btc)
    format_row("Estrategia Optimizada: ETH Intradía", res_opt_eth)
    format_row("Estrategia Optimizada: SOL Intradía", res_opt_sol)
    
    comb_color = "[bold green]" if comb_net > 0 else "[bold red]"
    table.add_row(
        "[bold yellow]PORTAFOLIO MULTI-ACTIVO (BTC + ETH + SOL)[/bold yellow]",
        f"[bold cyan]{comb_total}[/bold cyan]",
        f"[bold green]{comb_wr:.1f}%[/bold green]",
        f"{comb_color}${comb_net:+,.2f}[/]",
        f"{comb_color}{comb_net/1000.0*100:+.2f}%[/]",
        f"[bold magenta]{comb_pf:.2f}[/bold magenta]",
        "[dim green]Bajo riesgo[/dim green]"
    )

    console.print(table)

    if combined_trades:
        trade_table = Table(title=f"🔍 Muestra de Operaciones Ejecutadas (Primeras 10 de {comb_total})", border_style="yellow", show_header=True)
        trade_table.add_column("Hora", style="dim white")
        trade_table.add_column("Activo", style="bold yellow")
        trade_table.add_column("Tipo", style="bold")
        trade_table.add_column("Entrada", justify="right")
        trade_table.add_column("Salida", justify="right")
        trade_table.add_column("Desfase", justify="right", style="cyan")
        trade_table.add_column("PnL (USDC)", justify="right", style="bold")
        trade_table.add_column("Duración", justify="right", style="dim")
        trade_table.add_column("Motivo", style="white")

        for t in combined_trades[:10]:
            pnl_c = "[green]" if t.pnl_usdc > 0 else "[red]"
            type_c = "[green]YES (Bull)[/green]" if t.outcome == "YES" else "[red]NO (Bear)[/red]"
            trade_table.add_row(
                f"{int(t.timestamp//3600):02d}:{int((t.timestamp%3600)//60):02d}:{int(t.timestamp%60):02d}",
                t.asset,
                type_c,
                f"${t.entry_price:.3f}",
                f"${t.exit_price:.3f}",
                f"+{t.discrepancy_captured*100:.1f}¢",
                f"{pnl_c}${t.pnl_usdc:+.2f} ({t.pnl_pct:+.1f}%)[/]",
                f"{t.hold_duration_sec:.0f}s",
                t.exit_reason
            )
        console.print(trade_table)

if __name__ == "__main__":
    run_backtests()
