import asyncio
import sys

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, DuplicateKeyError

from core.utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseConnectionPool:
    """Singleton database connection pool manager with retry logic"""

    _instance: Optional['DatabaseConnectionPool'] = None
    _lock = asyncio.Lock()

    def __new__(cls) -> 'DatabaseConnectionPool':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._initialize_state()

    @classmethod
    def create_isolated(cls) -> 'DatabaseConnectionPool':
        """Create a non-singleton pool for multi-database mode."""
        instance = object.__new__(cls)
        instance._initialized = True
        instance._initialize_state()
        return instance

    def _initialize_state(self) -> None:
        """Initialize per-instance pool state."""
        self._lock = asyncio.Lock()
        self._client: Optional[AsyncIOMotorClient] = None
        self._database: Optional[AsyncIOMotorDatabase] = None
        if 'uvloop' in sys.modules:
            self._pool_size = 200  # Can handle more with uvloop
            self._max_idle_time = 600000  # 10 minutes
        else:
            self._pool_size = 100
            self._max_idle_time = 300000  # 5 minutes

    async def initialize(self, uri: str, database_name: str) -> None:
        """Initialize the connection pool"""
        async with self._lock:
            if self._client is None:
                self._client = AsyncIOMotorClient(
                    uri,
                    maxPoolSize=self._pool_size,
                    minPoolSize=20 if 'uvloop' in sys.modules else 10,
                    maxIdleTimeMS=self._max_idle_time,
                    serverSelectionTimeoutMS=15000,
                    connectTimeoutMS=20000,
                    socketTimeoutMS=20000,
                    retryWrites=True,
                    retryReads=True,
                    waitQueueTimeoutMS=10000 if 'uvloop' in sys.modules else 5000,
                    waitQueueMultiple=4 if 'uvloop' in sys.modules else 2,
                )
                try:
                    self._database = self._client[database_name]
                    await self._test_connection()
                except BaseException:
                    # A failed/cancelled ping must not turn the next startup
                    # into a successful no-op against an unusable client.
                    client, self._client = self._client, None
                    self._database = None
                    try:
                        client.close()
                    except Exception as e:
                        logger.exception(f"Failed to close incomplete MongoDB client: {e}")
                    raise
                if 'uvloop' in sys.modules:
                    logger.info(f"Database pool initialized with uvloop optimizations (pool size: {self._pool_size})")
                else:
                    logger.info(f"Database pool initialized with standard asyncio (pool size: {self._pool_size})")

    async def _test_connection(self, max_retries: int = 3) -> None:
        """Test database connection with retry logic"""
        for attempt in range(max_retries):
            try:
                await self._client.admin.command('ping')
                return
            except (ConnectionFailure, ServerSelectionTimeoutError) as e:
                if attempt == max_retries - 1:
                    logger.error(f"Database connection test failed after {max_retries} attempts: {e}")
                    raise
                await asyncio.sleep(2 ** attempt)  # Exponential backoff

    @property
    def database(self) -> AsyncIOMotorDatabase:
        """Get database instance"""
        if self._database is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._database

    @property
    def client(self) -> AsyncIOMotorClient:
        """Get client instance"""
        if self._client is None:
            raise RuntimeError("Client not initialized. Call initialize() first.")
        return self._client

    async def close(self) -> None:
        """Close the connection pool properly"""
        async with self._lock:
            client, self._client = self._client, None
            self._database = None
            if client is not None:
                try:
                    client.close()
                    await asyncio.sleep(0.1)
                    logger.info("Database connection pool closed")
                except Exception as e:
                    logger.error(f"Error closing database pool: {e}")

    async def get_collection(self, name: str):
        """Get a collection from the database"""
        return self.database[name]

    async def execute_with_retry(self, operation, *args, max_retries=3, **kwargs):
        """Execute database operation with retry logic"""
        last_exception = None

        for attempt in range(max_retries):
            try:
                result = await operation(*args, **kwargs)
                return result
            except (ConnectionFailure, ServerSelectionTimeoutError) as e:
                last_exception = e
                if attempt == max_retries - 1:
                    logger.error(f"Database operation failed after {max_retries} attempts: {e}")
                    raise
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            except DuplicateKeyError as dp:
                logger.warning("Duplicate key detected. Skipping.")
                raise
            except Exception as e:
                error_str = str(e)
                # Index conflicts are normal when index already exists with same keys
                if "IndexOptionsConflict" in error_str or "Index already exists" in error_str:
                    logger.debug(f"Index conflict (already exists): {e}")
                else:
                    logger.error(f"Unexpected database error: {e}")
                raise

        # This should never be reached, but satisfy static analysis
        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected error in execute_with_retry")


# Global instance
db_pool = DatabaseConnectionPool()
