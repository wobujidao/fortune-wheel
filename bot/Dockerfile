FROM python:3.13-slim

RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser
RUN apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/bot/

RUN mkdir -p /app/data && chown -R appuser:appuser /app

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/app/bot/entrypoint.sh"]
