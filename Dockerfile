FROM python:3.11-slim

# Evitar que Python escriba archivos .pyc y permitir logs sin buffer
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias del sistema si fueran necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements y luego instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Ejecutar el bot
CMD ["python", "main.py"]
