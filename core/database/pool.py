import asyncio
import sys

from typing import Optional

import backoff
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
                self._database = self._client[database_name]

                # Test connection
                await self._test_connection()
                if 'uvloop' in sys.modules:
                    logger.info(f"Database pool initialized with uvloop optimizations (pool size: {self._pool_size})")
                else:
                    logger.info(f"Database pool initialized with standard asyncio (pool size: {self._pool_size})")

    @backoff.on_exception(
        backoff.expo,
        (ConnectionFailure, ServerSelectionTimeoutError),
        max_tries=3,
        max_time=30
    )
    async def _test_connection(self) -> None:
        """Test database connection with retry logic"""
        await self._client.admin.command('ping')

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

                # Wait a bit for connections to close gracefully
                await asyncio.sleep(0.5)

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
                logger.error(f"Unexpected database error: {e}")
                raise

        # This should never be reached, but satisfy static analysis
        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected error in execute_with_retry")


# Global instance
db_pool = DatabaseConnectionPool()
