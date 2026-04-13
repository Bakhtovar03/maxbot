FROM python:3.13-slim

WORKDIR /app

# Копируем только requirements, чтобы кэшировать установку
COPY requirements.txt .

# Устанавливаем зависимости Python (если нужны пакеты с компиляцией, добавляем libffi-dev и build-essential)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libffi-dev \
        libssl-dev \
    && pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем весь проект
COPY . .

CMD ["python", "main.py"]
