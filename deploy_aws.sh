#!/bin/bash
set -e

echo "====================================================="
echo "   🚀 INSTALADOR AUTOMÁTICO PARA AWS UBUNTU (VIRGINIA)"
echo "   Polymarket Quantitative Market Maker 24/7"
echo "====================================================="

# 1. Actualizar repositorios e instalar paquetes base
sudo apt update -y
sudo apt install -y python3 python3-pip python3-venv git tmux curl htop

# 2. Configurar Entorno Virtual Python
if [ ! -d "venv" ]; then
    echo "📦 Creando entorno virtual Python..."
    python3 -m venv venv
fi

echo "📥 Instalando dependencias de ultra-baja latencia (uvloop + py-clob-client)..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Comprobar archivo .env
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
    else
        touch .env
    fi
    echo "⚠️ Se ha creado un archivo .env vacío. Por favor edítalo con tus credenciales:"
    echo "   nano .env"
fi

# 4. Crear Servicio Systemd para Auto-Reinicio 24/7
SERVICE_FILE="/etc/systemd/system/polymarket-bot.service"
CURRENT_DIR=$(pwd)
CURRENT_USER=$(whoami)

echo "⚙️ Configurando servicio 24/7 (systemd) para reinicio automático..."
sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=Polymarket Quantitative Market Maker Bot
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
ExecStart=$CURRENT_DIR/venv/bin/python3 $CURRENT_DIR/main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOL

sudo systemctl daemon-reload
sudo systemctl enable polymarket-bot.service

echo ""
echo "====================================================="
echo "✅ ¡INSTALACIÓN COMPLETADA CON ÉXITO EN AWS!"
echo "====================================================="
echo "Comandos útiles para gestionar tu bot en AWS:"
echo " • Iniciar servicio 24/7:      sudo systemctl start polymarket-bot"
echo " • Ver logs / pantalla en vivo: sudo journalctl -u polymarket-bot -f"
echo " • Detener el bot:             sudo systemctl stop polymarket-bot"
echo " • Reiniciar el bot:           sudo systemctl restart polymarket-bot"
echo " • O correrlo manual con GUI:  source venv/bin/activate && python3 main.py"
echo "====================================================="
