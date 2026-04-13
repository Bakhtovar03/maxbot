import logging
import os

import redis.asyncio as redis
from maxo import Bot, Dispatcher
from maxo.fsm.storages.redis import RedisStorage
from maxo.transport.long_polling import LongPolling

from config.config import load_config
from handlers.admin import admin_router
from handlers.user import user_router

config = load_config()
bot = Bot(config.bot.token)


def main():
    logging.basicConfig(level=logging.INFO)

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6379))
    redis_client = redis.Redis(
        host=redis_host,
        port=redis_port,
        decode_responses=True,
        db=1,
    )
    storage = RedisStorage(redis_client)
    dispatcher = Dispatcher(storage=storage)
    dispatcher.include(admin_router)
    dispatcher.include(user_router)
    LongPolling(dispatcher).run(bot, redis_client=redis_client)


if __name__ == "__main__":
    main()
