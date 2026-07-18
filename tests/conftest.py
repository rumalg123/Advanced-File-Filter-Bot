import os


# Application settings are validated at import time. Unit tests use inert values
# and never connect to Telegram, MongoDB, or Redis.
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "test-api-hash")
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("DATABASE_URI", "mongodb://localhost:27017/test")
os.environ.setdefault("REDIS_URI", "redis://localhost:6379/15")
os.environ.setdefault("ADMINS", "1")
os.environ.setdefault("CHANNELS", "0")
