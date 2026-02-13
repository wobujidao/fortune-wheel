from __future__ import annotations

import os
from pathlib import Path

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
WEBAPP_URL: str = os.environ["WEBAPP_URL"]
ADMIN_IDS: list[int] = [
    int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()
]
DB_PATH: str = os.environ.get("DB_PATH", "./data/fortune.db")
API_HOST: str = os.environ.get("API_HOST", "0.0.0.0")
API_PORT: int = int(os.environ.get("API_PORT", "8000"))

# Гарантируем, что директория для БД существует
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
