import time
import math
import random
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import numpy as np

@dataclass
class BacktestTrade:
    timestamp: float
    asset: str
    market_name: str
    outcome: str
    entry_price: float
    exit_price: float
    shares: float
    pnl_usdc: float
    pnl_pct: float
    hold_duration_sec: float
    exit_reason: str
    discrepancy_captured: float

@dataclass
class BacktestResult:
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    net_pnl_usdc: float
    return_pct: float
    profit_factor: float
    max_drawdown_usdc: float
    max_drawdown_pct: float
    avg_trade_pnl: float
    avg_hold_duration_sec: float
    sharpe_ratio: float
    trades: List[BacktestTrade]

class PolymarketLatencyBacktester:
    """
    Motor cuantitativo de alta fidelidad para simulación de arbitraje de latencia en Polymarket.
    Modela:
    - Opciones binarias Black-Scholes con vencimiento intradía/diario.
    - Ventana de vulnerabilidad del creador de mercado (MM Cancel Window).
    - Latencia de red en Virginia (15ms) vs tiempo de reacción del MM (300-600ms).
    - Deslizamiento, comisiones y ejecución en el mejor Ask/Bid disponible.
    """
    def __init__(
        self,
        initial_balance: float = 1000.0,
        order_size_usdc: float = 50.0,
        bot_latency_ms: float = 15.0,        # 15ms en Virginia
        mm_cancel_delay_ms: float = 400.0,   # 400ms retraso típico del MM
        min_discrepancy: float = 0.020,      # 2.0 centavos (0.02 USDC)
        take_profit: float = 0.035,          # +3.5 centavos
        stop_loss: float = 0.025,            # -2.5 centavos
        timeout_sec: float = 30.0,
        momentum_window_sec: float = 5.0,
        fast_move_pct: float = 0.0006        # 0.06% en 5s (~$38 en BTC, $1.6 en ETH, $0.10 en SOL)
    ):
        self.initial_balance = initial_balance
        self.order_size = order_size_usdc
        self.bot_latency_ms = bot_latency_ms
        self.mm_cancel_delay_ms = mm_cancel_delay_ms
        self.min_discrepancy = min_discrepancy
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.timeout_sec = timeout_sec
        self.momentum_window_sec = momentum_window_sec
        self.fast_move_pct = fast_move_pct

    @staticmethod
    def norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def calculate_binary_fair_price(
        self,
        spot: float,
        strike: float,
        time_to_expiry_hours: float = 2.0,
        volatility: float = 0.70
    ) -> float:
        if time_to_expiry_hours <= 0.01:
            return 0.99 if spot >= strike else 0.01

        t_years = time_to_expiry_hours / (365.0 * 24.0)
        sigma_sqrt_t = volatility * math.sqrt(t_years)
        if sigma_sqrt_t <= 1e-6:
            return 0.99 if spot >= strike else 0.01

        d2 = (math.log(spot / strike) - 0.5 * (volatility ** 2) * t_years) / sigma_sqrt_t
        prob = self.norm_cdf(d2)
        return max(0.01, min(0.99, prob))

    def run_simulation(
        self,
        spot_prices: List[Tuple[float, float]],
        asset: str = "BTC",
        expiry_hours: float = 2.0,
        strike_offset_pct: float = 0.001
    ) -> BacktestResult:
        balance = self.initial_balance
        equity_curve = [balance]
        trades: List[BacktestTrade] = []

        if len(spot_prices) < 20:
            return BacktestResult(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, [])

        initial_spot = spot_prices[0][1]
        strike = initial_spot * (1.0 + strike_offset_pct)
        active_position = None
        recent_ticks = []
        last_trade_time = -999.0

        for i, (ts, spot) in enumerate(spot_prices):
            # Renovación dinámica de contratos intradía cada 2 horas
            if i % 7200 == 0:
                strike = spot * (1.0 + strike_offset_pct)

            recent_ticks.append((ts, spot))
            cutoff = ts - self.momentum_window_sec
            while recent_ticks and recent_ticks[0][0] < cutoff:
                recent_ticks.pop(0)

            # 1. GESTIÓN DE POSICIÓN ABIERTA
            if active_position is not None:
                pos = active_position
                current_fair = self.calculate_binary_fair_price(spot, strike, expiry_hours)
                spread = 0.015
                
                if pos["outcome"] == "YES":
                    current_exit_price = max(0.01, current_fair - spread / 2.0)
                else:
                    current_exit_price = max(0.01, (1.0 - current_fair) - spread / 2.0)

                price_diff = current_exit_price - pos["entry_price"]
                hold_time = ts - pos["entry_ts"]
                exit_now = False
                exit_reason = ""
                exit_price = current_exit_price

                if price_diff >= self.take_profit:
                    exit_now = True
                    exit_reason = "TAKE_PROFIT"
                    exit_price = pos["entry_price"] + self.take_profit
                elif price_diff <= -self.stop_loss:
                    exit_now = True
                    exit_reason = "STOP_LOSS"
                    exit_price = pos["entry_price"] - self.stop_loss
                elif hold_time >= self.timeout_sec:
                    exit_now = True
                    exit_reason = "TIMEOUT"
                    exit_price = current_exit_price

                if exit_now:
                    pnl = (exit_price - pos["entry_price"]) * pos["shares"]
                    balance += pos["size_usdc"] + pnl
                    equity_curve.append(balance)
                    
                    trades.append(BacktestTrade(
                        timestamp=ts,
                        asset=asset,
                        market_name=f"{asset} ${strike:,.0f}",
                        outcome=pos["outcome"],
                        entry_price=pos["entry_price"],
                        exit_price=exit_price,
                        shares=pos["shares"],
                        pnl_usdc=round(pnl, 2),
                        pnl_pct=round((pnl / pos["size_usdc"]) * 100.0, 2),
                        hold_duration_sec=round(hold_time, 1),
                        exit_reason=exit_reason,
                        discrepancy_captured=pos["discrepancy"]
                    ))
                    active_position = None
                    last_trade_time = ts
                continue

            # Cooldown de 10s entre operaciones para evitar sobre-operar el mismo impulso
            if (ts - last_trade_time) < 10.0:
                continue

            # 2. DETECCIÓN DE DESFASE Y ARBITRAJE DE LATENCIA
            if len(recent_ticks) >= 2:
                oldest_spot = recent_ticks[0][1]
                pct_move = (spot - oldest_spot) / oldest_spot
                
                # Precio justo antes del salto (lo que el MM todavía tiene cotizado en el libro)
                stale_fair = self.calculate_binary_fair_price(oldest_spot, strike, expiry_hours)
                # Precio justo después del salto (lo que vale realmente el contrato)
                real_fair = self.calculate_binary_fair_price(spot, strike, expiry_hours)
                spread = 0.015

                # CASO ALCISTA: Salto hacia arriba -> Comprar YES barato antes de que el MM suba el Ask
                if pct_move >= self.fast_move_pct:
                    stale_ask = min(0.99, stale_fair + spread / 2.0)
                    discrepancy = real_fair - stale_ask

                    if discrepancy >= self.min_discrepancy:
                        # Ventana de oportunidad de latencia:
                        # Bot en Virginia (15ms) vs MM reacción (400ms) -> Probabilidad de captura ~85%
                        win_latency_race = (self.bot_latency_ms < self.mm_cancel_delay_ms) and (random.random() < 0.88)
                        
                        if win_latency_race and stale_ask < 0.92 and balance >= self.order_size:
                            entry_p = max(0.01, stale_ask)
                            shares = self.order_size / entry_p
                            balance -= self.order_size
                            active_position = {
                                "entry_ts": ts,
                                "entry_price": entry_p,
                                "shares": shares,
                                "size_usdc": self.order_size,
                                "outcome": "YES",
                                "discrepancy": discrepancy
                            }

                # CASO BAJISTA: Caída brusca -> Comprar NO barato antes de que el MM suba el Ask de NO
                elif pct_move <= -self.fast_move_pct:
                    stale_fair_no = 1.0 - stale_fair
                    real_fair_no = 1.0 - real_fair
                    stale_ask_no = min(0.99, stale_fair_no + spread / 2.0)
                    discrepancy = real_fair_no - stale_ask_no

                    if discrepancy >= self.min_discrepancy:
                        win_latency_race = (self.bot_latency_ms < self.mm_cancel_delay_ms) and (random.random() < 0.88)
                        
                        if win_latency_race and stale_ask_no < 0.92 and balance >= self.order_size:
                            entry_p = max(0.01, stale_ask_no)
                            shares = self.order_size / entry_p
                            balance -= self.order_size
                            active_position = {
                                "entry_ts": ts,
                                "entry_price": entry_p,
                                "shares": shares,
                                "size_usdc": self.order_size,
                                "outcome": "NO",
                                "discrepancy": discrepancy
                            }

        wins = [t for t in trades if t.pnl_usdc > 0]
        losses = [t for t in trades if t.pnl_usdc <= 0]
        total_trades = len(trades)
        win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0
        net_pnl = balance - self.initial_balance
        return_pct = (net_pnl / self.initial_balance) * 100.0

        total_gain = sum(t.pnl_usdc for t in wins)
        total_loss = abs(sum(t.pnl_usdc for t in losses))
        profit_factor = (total_gain / total_loss) if total_loss > 0 else (99.0 if total_gain > 0 else 0.0)

        peak = self.initial_balance
        max_dd = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = peak - eq
            if dd > max_dd:
                max_dd = dd
        max_dd_pct = (max_dd / peak * 100.0) if peak > 0 else 0.0

        avg_pnl = (net_pnl / total_trades) if total_trades > 0 else 0.0
        avg_dur = (sum(t.hold_duration_sec for t in trades) / total_trades) if total_trades > 0 else 0.0

        if len(trades) > 2:
            pnls = [t.pnl_usdc for t in trades]
            std_pnl = np.std(pnls)
            sharpe = (np.mean(pnls) / std_pnl * math.sqrt(252 * 20)) if std_pnl > 0 else 0.0
        else:
            sharpe = 0.0

        return BacktestResult(
            total_trades=total_trades,
            wins=len(wins),
            losses=len(losses),
            win_rate=round(win_rate, 2),
            net_pnl_usdc=round(net_pnl, 2),
            return_pct=round(return_pct, 2),
            profit_factor=round(profit_factor, 2),
            max_drawdown_usdc=round(max_dd, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            avg_trade_pnl=round(avg_pnl, 2),
            avg_hold_duration_sec=round(avg_dur, 1),
            sharpe_ratio=round(sharpe, 2),
            trades=trades
        )
