from redis import Redis
from app.config import settings

cache = Redis.from_url(settings.redis_url, decode_responses=True,
                       socket_connect_timeout=2, socket_timeout=2)
