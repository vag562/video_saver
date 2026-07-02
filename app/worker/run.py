from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from app.db.init_db import init_db


if __name__ == "__main__":
    settings = get_settings()
    init_db()
    connection = Redis.from_url(settings.redis_url)
    worker = Worker([Queue(settings.rq_queue_name, connection=connection)], connection=connection)
    worker.work(with_scheduler=True)
