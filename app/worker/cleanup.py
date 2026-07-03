import logging
import time

from app.core.config import get_settings
from app.db.init_db import init_db
from app.worker.tasks import cleanup_expired


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    init_db()
    while True:
        cleanup_expired()
        time.sleep(settings.cleanup_interval_seconds)
