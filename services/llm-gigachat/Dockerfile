FROM python:3.13-slim

WORKDIR /app

# Системные зависимости: gcc для сборки некоторых пакетов
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Сначала копируем requirements — так Docker кэширует установку пакетов
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Копируем код сервиса
COPY services/llm-gigachat/ /app/

# Папка для логов
RUN mkdir -p /app/logs

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]