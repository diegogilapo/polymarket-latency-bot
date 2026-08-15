import os
import sys
import csv
import logging
from datetime import datetime

# Asegurar codificación UTF-8 en consolas Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.logging import RichHandler

# Crear directorios para logs y datos si no existen
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

console = Console(force_terminal=True)

# Configurar logging estándar hacia archivo
file_handler = logging.FileHandler("logs/events.log", encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler.setFormatter(file_formatter)

# Configurar Rich Handler para la consola
rich_handler = RichHandler(
    console=console,
    rich_tracebacks=True,
    markup=True,
    show_time=True,
    show_path=False
)
rich_handler.setLevel(logging.INFO)

# Configurar logger raíz
logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, rich_handler]
)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

class TradeLogger:
    """Registrador de operaciones simuladas y reales en archivo CSV"""
    CSV_PATH = "data/trades.csv"
    CSV_HEADERS = [
        "timestamp_entry",
        "timestamp_exit",
        "market_question",
        "token_id",
        "outcome",
        "side",
        "entry_price",
        "exit_price",
        "shares_count",
        "size_usdc",
        "pnl_usdc",
        "pnl_percentage",
        "exit_reason",
        "lag_duration_ms",
        "btc_price_entry",
        "btc_price_exit",
        "simulated_balance_after"
    ]

    def __init__(self):
        self._init_csv()

    def _init_csv(self):
        if not os.path.exists(self.CSV_PATH):
            with open(self.CSV_PATH, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(self.CSV_HEADERS)

    def log_trade(self, trade_data: dict):
        try:
            with open(self.CSV_PATH, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                row = [trade_data.get(header, "") for header in self.CSV_HEADERS]
                writer.writerow(row)
        except Exception as e:
            logging.getLogger("TradeLogger").error(f"Error escribiendo trade en CSV: {e}")

trade_logger = TradeLogger()
