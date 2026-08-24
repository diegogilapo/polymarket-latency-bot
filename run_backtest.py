import sys
import os

if sys.platform.startswith("win"):
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    if hasattr(sys.stderr, "reconfigure"):
        try: sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass

import time
import math
import random
import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from src.engine.backtester import PolymarketLatencyBacktester, BacktestResult

console = Console()

def fetch_real_market_ticks(symbol: str):
    """Descarga datos reales de mercado (1m klines expandidas a micro-ticks) desde Binance"""
    client = httpx.Client(timeout=8.0)
    all_ticks = []
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=1000"
    
    try:
        resp = client.get(url)
        if resp.status_code == 200:
            candles = resp.json()
            for c in candles:
                ts_open = float(c[0]) / 1000.0
                open_p = float(c[1])
                high_p = float(c[2])
                low_p = float(c[3])
                close_p = float(c[4])
                
                # Expandir cada vela de 1m en 4 micro-ticks para simular la trayectoria exacta
                all_ticks.append((ts_open, open_p))
                all_ticks.append((ts_open + 15.0, high_p if close_p >= open_p else low_p))
                all_ticks.append((ts_open + 30.0, low_p if close_p >= open_p else high_p))
                all_ticks.append((ts_open + 45.0, close_p))
    except Exception as e:
        console.print(f"[dim red]Error descargando {symbol}: {e}[/dim red]")

    return all_ticks

def run_comprehensive_backtest():
    console.print(Panel("[bold cyan]🚀 EJECUTANDO BACKTESTING CUANTITATIVO (MOTOR HÍBRIDO SNIPER + MAKER OPTIMIZADO)[/bold cyan]\n"
                        "[dim]• Modelo: Latency Arbitrage Sniper (Taker en Impulsos) + Spread Capture (Maker)\n"
                        "• Período: Últimas 16.6 Horas de Mercado Real (4,000 Micro-ticks por Activo)\n"
                        "• Parámetros: 15ms Latencia en Virginia vs 400ms Lag Retail | Spread Objetivo: +3.0¢\n"
                        "• Gestión de Riesgo: Stop Loss Estricto (-2.0¢) y Take Profit (+3.0¢)[/dim]",
                        border_style="cyan"))

    assets = [
        ("BTCUSDT", "BTC"),
        ("ETHUSDT", "ETH"),
        ("SOLUSDT", "SOL"),
        ("DOGEUSDT", "DOGE"),
        ("XRPUSDT", "XRP")
    ]
    
    # 1. Backtest con Capital Real Actual ($43.64 USDC) y Órdenes de $5.0 USDC
    bt_real_cap = PolymarketLatencyBacktester(
        initial_balance=43.64,
        order_size_usdc=5.0,
        bot_latency_ms=15.0,
        mm_cancel_delay_ms=400.0,
        min_discrepancy=0.015,  # 1.5¢ mínimo de desfase
        take_profit=0.030,      # +3.0¢
        stop_loss=0.020,        # -2.0¢
        timeout_sec=90.0,
        momentum_window_sec=60.0,
        fast_move_pct=0.0004    # 0.04% en 1m
    )

    # 2. Backtest Institucional ($1,000 USDC) y Órdenes de $50 USDC
    bt_inst_cap = PolymarketLatencyBacktester(
        initial_balance=1000.0,
        order_size_usdc=50.0,
        bot_latency_ms=15.0,
        mm_cancel_delay_ms=400.0,
        min_discrepancy=0.015,
        take_profit=0.030,
        stop_loss=0.020,
        timeout_sec=90.0,
        momentum_window_sec=60.0,
        fast_move_pct=0.0004
    )

    all_results_real = []
    all_results_inst = []

    table = Table(title="📊 RESULTADOS DETALLADOS POR CRIPTOMONEDA (Últimas 16.6h Reales)", border_style="green", show_header=True)
    table.add_column("Cripto", style="bold yellow", no_wrap=True)
    table.add_column("Micro-Ticks", justify="right", style="dim white")
    table.add_column("Trades", justify="right", style="bold white")
    table.add_column("Ganados / Perdidos", justify="center", style="bold white")
    table.add_column("Win Rate (%)", justify="right", style="bold green")
    table.add_column("Profit Factor", justify="right", style="bold cyan")
    table.add_column("PnL ($43.64 Cap)", justify="right", style="bold green")
    table.add_column("Retorno %", justify="right", style="bold green")
    table.add_column("Max Drawdown", justify="right", style="bold red")
    table.add_column("Sharpe Ratio", justify="right", style="bright_yellow")

    for pair, asset in assets:
        console.print(f"📥 Descargando historial de alta frecuencia para [bold yellow]{asset}[/bold yellow]...")
        ticks = fetch_real_market_ticks(pair)
        if not ticks:
            continue

        res_real = bt_real_cap.run_simulation(ticks, asset=asset, expiry_hours=2.0)
        res_inst = bt_inst_cap.run_simulation(ticks, asset=asset, expiry_hours=2.0)
        all_results_real.append(res_real)
        all_results_inst.append(res_inst)

        pnl_color = "[green]" if res_real.net_pnl_usdc >= 0 else "[red]"
        table.add_row(
            f"[bold yellow]{asset}[/bold yellow]",
            f"{len(ticks):,}",
            f"{res_real.total_trades}",
            f"[green]{res_real.wins}[/green] / [red]{res_real.losses}[/red]",
            f"{res_real.win_rate:.1f}%",
            f"{res_real.profit_factor:.2f}",
            f"{pnl_color}+${res_real.net_pnl_usdc:.2f} USDC[/]" if res_real.net_pnl_usdc >= 0 else f"{pnl_color}-${abs(res_real.net_pnl_usdc):.2f} USDC[/]",
            f"{pnl_color}+{res_real.return_pct:.1f}%[/]" if res_real.return_pct >= 0 else f"{pnl_color}{res_real.return_pct:.1f}%[/]",
            f"-{res_real.max_drawdown_pct:.1f}% (${res_real.max_drawdown_usdc:.2f})",
            f"{res_real.sharpe_ratio:.2f}"
        )

    console.print("\n", table)

    # Resumen Global
    total_trades_real = sum(r.total_trades for r in all_results_real)
    total_wins_real = sum(r.wins for r in all_results_real)
    total_losses_real = sum(r.losses for r in all_results_real)
    total_pnl_real = sum(r.net_pnl_usdc for r in all_results_real)
    avg_winrate_real = (total_wins_real / total_trades_real * 100.0) if total_trades_real > 0 else 0.0

    total_pnl_inst = sum(r.net_pnl_usdc for r in all_results_inst)
    valid_pfs = [r.profit_factor for r in all_results_real if r.profit_factor > 0]
    avg_pf = sum(valid_pfs) / len(valid_pfs) if valid_pfs else 0.0

    summary_box = (
        f"[bold white]🏦 Capital Inicial:[/] [bold cyan]$43.64 USDC[/bold cyan]  │  "
        f"[bold white]Beneficio Neto Simulado:[/] [bold green]+${total_pnl_real:.2f} USDC (+{(total_pnl_real/43.64)*100:.1f}% en 16.6h)[/bold green]\n"
        f"[bold white]🎯 Operaciones Totales:[/] [bold white]{total_trades_real} trades[/bold white] ([green]{total_wins_real} ganados[/green] / [red]{total_losses_real} perdidos[/red])  │  "
        f"[bold white]Acierto Global (Win Rate):[/] [bold green]{avg_winrate_real:.1f}%[/bold green]  │  "
        f"[bold white]Profit Factor:[/] [bold cyan]{avg_pf:.2f}[/bold cyan]\n"
        f"[bold white]📈 Proyección con Cuenta Institucional ($1,000 USDC):[/] [bold green]+${total_pnl_inst:.2f} USDC (+{(total_pnl_inst/1000.0)*100:.1f}%)[/bold green]"
    )
    console.print(Panel(summary_box, title="🏆 RESUMEN CUANTITATIVO GLOBAL (MOTOR OPTIMIZADO)", border_style="gold1"))

if __name__ == "__main__":
    run_comprehensive_backtest()
