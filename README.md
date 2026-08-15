# 🚀 Polymarket BTC Latency Arbitrage & Paper Trading Bot

Bot de arbitraje de latencia y trading algorítmico de alta frecuencia para **Polymarket**, diseñado para detectar desfases en tiempo real entre los precios de **Bitcoin** en exchanges globales (**Binance Futures, Binance Spot y Coinbase**) y los libros de órdenes del CLOB de Polymarket.

Incluye un **Motor de Simulación (Paper Trading / Demo)** completo para operar contra libros reales con **cero riesgo de capital**.

---

## 📋 Características Principales

* ⚡ **Feeds en Tiempo Real (WebSocket)**: Conexión asíncrona a Binance USD-M Futures (`btcusdt@aggTrade`), Binance Spot (`btcusdt@trade`) y Coinbase Pro (`BTC-USD ticker`).
* 🎯 **Descubrimiento Dinámico de Mercados**: Auto-descubre los mercados activos de Bitcoin en Polymarket vía Gamma API y se suscribe al CLOB WebSocket.
* 🧠 **Modelo de Fair Value & Momento**: Calcula la probabilidad implícita en milisegundos cuando detecta un salto de velocidad en el precio de BTC.
* 🛡️ **Simulación Realista de Ejecución (Paper Trading)**:
  * Verifica liquidez y profundidad real en el libro de órdenes.
  * Añade penalización de latencia de red configurable (ej. 25ms de viaje a EE.UU.) para validar si la orden seguiría viva.
  * Gestión automática de posiciones: **Take Profit**, **Stop Loss** y **Timeout Exit** (cierre al reequilibrarse el mercado).
* 📊 **Panel en Vivo & Exportación CSV**:
  * Dashboard visual en consola con precios de BTC, delta de velocidad, mercados seguidos, balance virtual y Win Rate.
  * Exporta cada operación a `data/trades.csv` y logs detallados a `logs/events.log`.
* ☁️ **Listo para GitHub & Render.com**: Incluye `render.yaml`, `Procfile`, `Dockerfile` y `.gitignore`.

---

## 🛠️ Instalación y Uso Local

### 1. Clonar el repositorio y entrar en la carpeta
```bash
git clone <URL_DE_TU_REPOSITORIO>
cd "Polymarket bot"
```

### 2. Crear un entorno virtual e instalar dependencias
```bash
python -m venv venv

# En Windows:
venv\Scripts\activate

# En Linux/Mac:
source venv/bin/activate

# Instalar librerías:
pip install -r requirements.txt
```

### 3. Configurar variables de entorno
Crea tu archivo `.env` copiando la plantilla:
```bash
cp .env.example .env
```
*(Por defecto, `SIMULATION_MODE=True`, por lo que no necesitas ninguna clave privada para probarlo en modo Demo).*

### 4. Ejecutar el bot
```bash
python main.py
```

---

## ☁️ Despliegue en Render.com (24/7 en la Nube)

Para que el bot corra 24/7 con baja latencia (~10-15ms a los servidores de Polymarket en Virginia):

### Paso 1: Subir el proyecto a GitHub
1. Inicializa tu repositorio Git local:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: Polymarket Latency Bot"
   ```
2. Crea un repositorio en [GitHub.com](https://github.com/new).
3. Vincula y sube el código:
   ```bash
   git remote add origin https://github.com/TU_USUARIO/TU_REPOSITORIO.git
   git branch -M main
   git push -u origin main
   ```

### Paso 2: Crear el servicio en Render.com
1. Inicia sesión en [Render.com](https://render.com).
2. Haz clic en **New +** y selecciona **Background Worker** (o usa el botón *Blueprint* conectando el archivo `render.yaml`).
3. Conecta tu repositorio de GitHub.
4. Configura los parámetros:
   * **Name:** `polymarket-bot`
   * **Region:** `US East (Ohio)` *(Es la más cercana a Virginia `us-east-1`)*
   * **Runtime:** `Python 3`
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `python main.py`
5. En la sección **Environment Variables**, añade tus variables o mantén las de simulación:
   * `SIMULATION_MODE` = `True`
   * `SIMULATION_INITIAL_BALANCE` = `1000.0`
6. Haz clic en **Create Background Worker**. ¡Listo! El bot estará activo 24/7 y verás los logs en vivo en la consola de Render.

---

## 📊 Parámetros Clave en `.env`

| Variable | Descripción | Valor por Defecto |
| :--- | :--- | :--- |
| `SIMULATION_MODE` | `True` para Demo virtual, `False` para dinero real | `True` |
| `SIMULATION_INITIAL_BALANCE` | Capital virtual inicial en USDC | `1000.0` |
| `SIMULATED_NETWORK_LATENCY_MS` | Delay de red simulado (en milisegundos) | `25` |
| `MIN_PRICE_DISCREPANCY` | Desfase mínimo en USDC para disparar orden | `0.04` (4 centavos) |
| `ORDER_SIZE_USDC` | Tamaño de cada posición en USDC | `50.0` |
| `TAKE_PROFIT_DELTA` | Ganancia objetivo por acción | `0.08` (+8¢) |
| `STOP_LOSS_DELTA` | Pérdida máxima permitida por acción | `0.06` (-6¢) |
| `POSITION_TIMEOUT_SECONDS` | Segundos para cerrar posición si el mercado se reequilibra | `45` |
| `BTC_FAST_MOVE_THRESHOLD_USD`| Salto mínimo de BTC en $ para considerar impulso | `30.0` |

---

## 📈 Análisis de Resultados

Todas las operaciones simuladas o reales se guardan en tiempo real en:
* `data/trades.csv`: Abre este archivo en Excel o Google Sheets para analizar métricas:
  * Precio de entrada vs. salida.
  * Duración exacta del desfase (en ms).
  * Ganancia neta (USDC) y porcentaje de retorno.
  * Precio de BTC al entrar y al salir.
* `logs/events.log`: Historial completo de ticks, conexiones y eventos del sistema.
