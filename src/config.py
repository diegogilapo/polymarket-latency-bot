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
    # Modo de Operación (Dinero Real automático si hay clave privada)
    simulation_mode: bool = field(default_factory=lambda: get_env_bool("SIMULATION_MODE", False if os.getenv("POLYMARKET_PRIVATE_KEY") else True))
    simulation_initial_balance: float = field(default_factory=lambda: get_env_float("SIMULATION_INITIAL_BALANCE", 48.99))
    simulated_network_latency_ms: int = field(default_factory=lambda: get_env_int("SIMULATED_NETWORK_LATENCY_MS", 15))

    # --- ESTRATEGIA DE MARKET MAKING CUANTITATIVO CON ÓRDENES LÍMITE (MAKER ONLY) ---
    # Captura sistemática de spread y arbitraje de precios erróneos
    target_spread_cents: float = field(default_factory=lambda: get_env_float("TARGET_SPREAD_CENTS", 0.030)) # 3.0¢ de spread
    min_spread_cents: float = field(default_factory=lambda: get_env_float("MIN_SPREAD_CENTS", 0.018))    # 1.8¢ spread mínimo
    order_size_usdc: float = field(default_factory=lambda: get_env_float("ORDER_SIZE_USDC", 15.0))
    
    # --- MÓDULO A: INTERÉS COMPUESTO AUTOMÁTICO (AUTO-COMPOUNDING) ---
    auto_compounding: bool = field(default_factory=lambda: get_env_bool("AUTO_COMPOUNDING", True))
    compounding_allocation_pct: float = field(default_factory=lambda: get_env_float("COMPOUNDING_ALLOCATION_PCT", 0.08)) # 8% del balance por orden límite
    min_order_size_usdc: float = field(default_factory=lambda: get_env_float("MIN_ORDER_SIZE_USDC", 15.0))
    max_order_size_usdc: float = field(default_factory=lambda: get_env_float("MAX_ORDER_SIZE_USDC", 1500.0))
    max_inventory_per_market: float = field(default_factory=lambda: get_env_float("MAX_INVENTORY_PER_MARKET", 1000.0))
    inventory_skew_factor: float = field(default_factory=lambda: get_env_float("INVENTORY_SKEW_FACTOR", 0.00008))
    
    # Control Estricto de Exposición y Protección de Capital
    max_active_positions: int = field(default_factory=lambda: get_env_int("MAX_ACTIVE_POSITIONS", 4)) # Máximo 4 mercados con compras simultáneas
    max_total_exposure_pct: float = field(default_factory=lambda: get_env_float("MAX_TOTAL_EXPOSURE_PCT", 0.35)) # Máximo 35% de la cuenta invertida
    min_trade_profit_cents: float = field(default_factory=lambda: get_env_float("MIN_TRADE_PROFIT_CENTS", 0.020)) # +2.0¢ de beneficio mínimo al vender
    
    # Cancelación ultra-rápida ante volatilidad tóxica (0.15% en 3s)
    fast_volatility_cancel_pct: float = field(default_factory=lambda: get_env_float("FAST_VOLATILITY_CANCEL_PCT", 0.0015))
    momentum_window_seconds: float = field(default_factory=lambda: get_env_float("MOMENTUM_WINDOW_SECONDS", 3.0))

    # Activos Cripto Monitorizados (15 Criptomonedas de Mayor Liquidez)
    monitored_assets: List[str] = field(
        default_factory=lambda: get_env_list("MONITORED_ASSETS", [
            "BTC", "ETH", "SOL", "DOGE", "XRP",
            "ADA", "AVAX", "LINK", "BNB", "NEAR",
            "SUI", "PEPE", "SHIB", "LTC", "DOT"
        ])
    )

    # Búsqueda y Filtrado en Polymarket
    polymarket_search_keywords: List[str] = field(
        default_factory=lambda: get_env_list("POLYMARKET_SEARCH_KEYWORDS", [
            "Bitcoin", "BTC", "Ethereum", "ETH", "Solana", "SOL", "Dogecoin", "DOGE", "XRP", "Ripple",
            "Cardano", "ADA", "Avalanche", "AVAX", "Chainlink", "LINK", "BNB", "Binance", "Near",
            "Sui", "Pepe", "Shiba", "SHIB", "Litecoin", "LTC", "Polkadot", "DOT", "Crypto", "Price", "Hit", "Reach", "Above", "Dip"
        ])
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
