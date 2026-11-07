import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("SECRET_SANTA_DB", str(BASE_DIR / "secret_santa.db")))
SEED_PATH = Path(os.environ.get("SECRET_SANTA_SEED", str(BASE_DIR / "seed.json")))

# Admin PIN/password for managing setup before going live (default: "tomten")
ADMIN_PASSWORD = os.environ.get("SECRET_SANTA_ADMIN_PASSWORD", "tomten")

# DEV_MODE is True by default during development unless SECRET_SANTA_DEV_MODE=0
DEV_MODE_ENV = os.environ.get("SECRET_SANTA_DEV_MODE", "1").lower() in ("1", "true", "yes")
