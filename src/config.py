import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

def get_env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes", "y", "t")

def get_env_float(name: str, default: float = 0.0) -> float:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default

def get_env_int(name: str, default: int = 0) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default

def get_env_list(name: str, default: List[str] = None) -> List[str]:
    val = os.getenv(name)
    if not val:
        return default or []
    return [item.strip() for item in val.split(",") if item.strip()]

@dataclass
class BotConfig:
    # Modo de Operación
    simulation_mode: bool = field(default_factory=lambda: get_env_bool("SIMULATION_MODE", True))
    simulation_initial_balance: float = field(default_factory=lambda: get_env_float("SIMULATION_INITIAL_BALANCE", 1000.0))
    simulated_network_latency_ms: int = field(default_factory=lambda: get_env_int("SIMULATED_NETWORK_LATENCY_MS", 25))

    # Parámetros de Trading
    min_price_discrepancy: float = field(default_factory=lambda: get_env_float("MIN_PRICE_DISCREPANCY", 0.04))
    order_size_usdc: float = field(default_factory=lambda: get_env_float("ORDER_SIZE_USDC", 50.0))
    take_profit_delta: float = field(default_factory=lambda: get_env_float("TAKE_PROFIT_DELTA", 0.08))
    stop_loss_delta: float = field(default_factory=lambda: get_env_float("STOP_LOSS_DELTA", 0.06))
    position_timeout_seconds: int = field(default_factory=lambda: get_env_int("POSITION_TIMEOUT_SECONDS", 45))

    # Parámetros de Análisis de BTC
    btc_momentum_window_seconds: float = field(default_factory=lambda: get_env_float("BTC_MOMENTUM_WINDOW_SECONDS", 5.0))
    btc_fast_move_threshold_usd: float = field(default_factory=lambda: get_env_float("BTC_FAST_MOVE_THRESHOLD_USD", 30.0))
    polymarket_search_keywords: List[str] = field(default_factory=lambda: get_env_list("POLYMARKET_SEARCH_KEYWORDS", ["Bitcoin", "BTC"]))

    # Endpoints de API y WebSockets
    binance_spot_ws_url: str = "wss://stream.binance.com:9443/ws/btcusdt@trade"
    binance_futures_ws_url: str = "wss://fstream.binance.com/ws/btcusdt@aggTrade"
    coinbase_ws_url: str = "wss://ws-feed.exchange.coinbase.com"
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    polymarket_clob_http_url: str = "https://clob.polymarket.com"

    # Credenciales Polymarket (para modo real)
    polymarket_private_key: str = field(default_factory=lambda: os.getenv("POLYMARKET_PRIVATE_KEY", ""))
    polymarket_funder_address: str = field(default_factory=lambda: os.getenv("POLYMARKET_FUNDER_ADDRESS", ""))
    polymarket_api_key: str = field(default_factory=lambda: os.getenv("POLYMARKET_API_KEY", ""))
    polymarket_api_secret: str = field(default_factory=lambda: os.getenv("POLYMARKET_API_SECRET", ""))
    polymarket_passphrase: str = field(default_factory=lambda: os.getenv("POLYMARKET_PASSPHRASE", ""))

config = BotConfig()
