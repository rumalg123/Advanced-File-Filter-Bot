import asyncio
import sys

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, DuplicateKeyError

from core.constants import DatabaseConstants
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
            self._client: Optional[AsyncIOMotorClient] = None
            self._database: Optional[AsyncIOMotorDatabase] = None
            if 'uvloop' in sys.modules:
                self._pool_size = DatabaseConstants.POOL_SIZE_UVLOOP
                self._max_idle_time = DatabaseConstants.MAX_IDLE_TIME_UVLOOP
            else:
                self._pool_size = DatabaseConstants.POOL_SIZE_DEFAULT
                self._max_idle_time = DatabaseConstants.MAX_IDLE_TIME_DEFAULT

    async def initialize(self, uri: str, database_name: str) -> None:
        """Initialize the connection pool"""
        async with self._lock:
            if self._client is None:
                self._client = AsyncIOMotorClient(
                    uri,
                    maxPoolSize=self._pool_size,
                    minPoolSize=DatabaseConstants.MIN_POOL_SIZE_UVLOOP if 'uvloop' in sys.modules else DatabaseConstants.MIN_POOL_SIZE_DEFAULT,
                    maxIdleTimeMS=self._max_idle_time,
                    serverSelectionTimeoutMS=DatabaseConstants.SERVER_SELECTION_TIMEOUT,
                    connectTimeoutMS=DatabaseConstants.CONNECT_TIMEOUT,
                    socketTimeoutMS=DatabaseConstants.SOCKET_TIMEOUT,
                    retryWrites=True,
                    retryReads=True,
                    waitQueueTimeoutMS=DatabaseConstants.WAIT_QUEUE_TIMEOUT_UVLOOP if 'uvloop' in sys.modules else DatabaseConstants.WAIT_QUEUE_TIMEOUT_DEFAULT,
                    waitQueueMultiple=DatabaseConstants.WAIT_QUEUE_MULTIPLE_UVLOOP if 'uvloop' in sys.modules else DatabaseConstants.WAIT_QUEUE_MULTIPLE_DEFAULT,
                )
                self._database = self._client[database_name]

                # Test connection
                await self._test_connection()
                if 'uvloop' in sys.modules:
                    logger.info(f"Database pool initialized with uvloop optimizations (pool size: {self._pool_size})")
                else:
                    logger.info(f"Database pool initialized with standard asyncio (pool size: {self._pool_size})")

    async def _test_connection(self, max_retries: int = DatabaseConstants.MAX_RETRIES) -> None:
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
        if self._client:
            try:
                # Close all connections in the pool
                self._client.close()

                # Wait for pending operations to complete
                await asyncio.sleep(DatabaseConstants.CLOSE_SLEEP_DELAY)

                self._client = None
                self._database = None
                logger.info("Database connection pool closed")
            except Exception as e:
                logger.error(f"Error closing database pool: {e}")
                self._client = None
                self._database = None

    async def get_collection(self, name: str):
        """Get a collection from the database"""
        return self.database[name]

    async def execute_with_retry(self, operation, *args, max_retries=DatabaseConstants.MAX_RETRIES, **kwargs):
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
