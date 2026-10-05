"""Heartbeat and bounded Sandbox data jobs; never submits orders."""
import logging
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from redis import Redis
from redis.exceptions import RedisError, LockError
from sqlalchemy import text, select
from sqlalchemy.exc import SQLAlchemyError
from app.config import settings
from app.db import SessionLocal
from app.models import BrokerConnection
from app.market_data import queue_sync, sync_user

logging.basicConfig(level=logging.INFO, format='{"level":"%(levelname)s","message":"%(message)s"}')
running = True


def shutdown(*_):
    global running
    running = False


def main():
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    cache = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
    last_heartbeat = next_schedule = 0
    future = None

    def execute(user_id):
        lock = cache.lock(f'market:lock:{user_id}', timeout=600, blocking=False)
        if not lock.acquire(blocking=False):
            return
        try:
            sync_user(user_id)
        finally:
            try:
                lock.release()
            except LockError:
                logging.error('market_data_lock_expired')

    with ThreadPoolExecutor(max_workers=1) as executor:
        while running:
            try:
                now = time.monotonic()
                if now - last_heartbeat >= 10:
                    with SessionLocal() as db:
                        db.execute(text("SELECT 1"))
                    cache.set("worker:heartbeat", str(time.time()), ex=45)
                    last_heartbeat = now
                if now >= next_schedule:
                    with SessionLocal() as db:
                        users = db.scalars(select(BrokerConnection.user_id).where(
                            BrokerConnection.status != 'DISCONNECTED', BrokerConnection.account_id.is_not(None))).all()
                    for user_id in users:
                        queue_sync(cache, user_id)
                    next_schedule = now + settings.market_sync_seconds
                if future and future.done():
                    try:
                        future.result()
                    except Exception:
                        # Do not log exception arguments: driver/network errors may contain sensitive context.
                        logging.error('market_data_job_failed')
                    future = None
                if future is None:
                    user_id = cache.rpop('market:queue')
                    if user_id:
                        future = executor.submit(execute, user_id)
            except (RedisError, SQLAlchemyError):
                logging.error("worker_dependency_unavailable")
            time.sleep(1)


if __name__ == "__main__":
    main()
