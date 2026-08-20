import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()

def get_env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None: return default
    return val.strip().lower() in ("true", "1", "yes", "y", "t")

def get_env_float(name: str, default: float = 0.0) -> float:
    val = os.getenv(name)
    if val is None: return default
    try: return float(val)
    except ValueError: return default

def get_env_int(name: str, default: int = 0) -> int:
    val = os.getenv(name)
    if val is None: return default
    try: return int(val)
    except ValueError: return default

def get_env_list(name: str, default: List[str] = None) -> List[str]:
    val = os.getenv(name)
    if not val: return default or []
    return [item.strip() for item in val.split(",") if item.strip()]

@dataclass
class BotConfig:
    # Modo de Operación
    simulation_mode: bool = field(default_factory=lambda: get_env_bool("SIMULATION_MODE", True))
    simulation_initial_balance: float = field(default_factory=lambda: get_env_float("SIMULATION_INITIAL_BALANCE", 1000.0))
    simulated_network_latency_ms: int = field(default_factory=lambda: get_env_int("SIMULATED_NETWORK_LATENCY_MS", 15))

    # --- ESTRATEGIA DE ARBITRAJE ESTRUCTURAL DE PARIDAD BINARIA (100% RISK-FREE) ---
    # Se ejecuta cuando la suma de compra (YES Ask + NO Ask) es inferior a 1.00 USDC
    max_combined_ask_sum: float = field(default_factory=lambda: get_env_float("MAX_COMBINED_ASK_SUM", 0.992))
    min_parity_profit_pct: float = field(default_factory=lambda: get_env_float("MIN_PARITY_PROFIT_PCT", 0.008)) # 0.8% mínimo
    min_share_depth: float = field(default_factory=lambda: get_env_float("MIN_SHARE_DEPTH", 10.0))
    
    # Gestión de Capital Dinámico por Liquidez
    dynamic_sizing: bool = field(default_factory=lambda: get_env_bool("DYNAMIC_SIZING", True))
    max_order_size_usdc: float = field(default_factory=lambda: get_env_float("MAX_ORDER_SIZE_USDC", 500.0))
    min_order_size_usdc: float = field(default_factory=lambda: get_env_float("MIN_ORDER_SIZE_USDC", 25.0))
    order_size_usdc: float = field(default_factory=lambda: get_env_float("ORDER_SIZE_USDC", 100.0))

    # Activos Cripto Monitorizados
    monitored_assets: List[str] = field(default_factory=lambda: get_env_list("MONITORED_ASSETS", ["BTC", "ETH", "SOL", "DOGE", "XRP"]))
    momentum_window_seconds: float = field(default_factory=lambda: get_env_float("MOMENTUM_WINDOW_SECONDS", 4.0))
    fast_move_pct_threshold: float = field(default_factory=lambda: get_env_float("FAST_MOVE_PCT_THRESHOLD", 0.0018))

    # Búsqueda en Polymarket
    polymarket_search_keywords: List[str] = field(
        default_factory=lambda: get_env_list("POLYMARKET_SEARCH_KEYWORDS", ["Bitcoin", "BTC", "Ethereum", "ETH", "Solana", "SOL", "Dogecoin", "DOGE", "XRP", "Crypto", "Price", "Hit", "Reach", "Above", "Dip"])
    )

    # Endpoints de API y WebSockets
    coinbase_ws_url: str = "wss://ws-feed.exchange.coinbase.com"
    kraken_ws_url: str = "wss://ws.kraken.com"
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    polymarket_clob_http_url: str = "https://clob.polymarket.com"

    # Credenciales Polymarket
    polymarket_private_key: str = field(default_factory=lambda: os.getenv("POLYMARKET_PRIVATE_KEY", ""))
    polymarket_funder_address: str = field(default_factory=lambda: os.getenv("POLYMARKET_FUNDER_ADDRESS", ""))
    polymarket_api_key: str = field(default_factory=lambda: os.getenv("POLYMARKET_API_KEY", ""))
    polymarket_api_secret: str = field(default_factory=lambda: os.getenv("POLYMARKET_API_SECRET", ""))
    polymarket_passphrase: str = field(default_factory=lambda: os.getenv("POLYMARKET_PASSPHRASE", ""))

config = BotConfig()
