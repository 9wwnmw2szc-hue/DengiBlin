"""Infrastructure heartbeat only. Never substitutes invented market data."""
import logging
import signal
import time
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.config import settings
from app.db import SessionLocal

logging.basicConfig(level=logging.INFO, format='{"level":"%(levelname)s","message":"%(message)s"}')
running = True


def shutdown(*_):
    global running
    running = False


def main():
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    cache = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
    while running:
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
            cache.set("worker:heartbeat", str(time.time()), ex=45)
        except (RedisError, SQLAlchemyError):
            logging.error("worker_dependency_unavailable")
        time.sleep(10)


if __name__ == "__main__":
    main()
