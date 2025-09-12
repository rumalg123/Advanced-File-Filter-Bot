"""
Multi-database pool manager for handling multiple MongoDB connections
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from enum import Enum

from motor.motor_asyncio import AsyncIOMotorCollection

from core.database.pool import DatabaseConnectionPool
from core.utils.logger import get_logger

logger = get_logger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states"""
    CLOSED = "CLOSED"      # Normal operation
    OPEN = "OPEN"          # Failing, reject requests
    HALF_OPEN = "HALF_OPEN"  # Testing if service recovered


@dataclass
class CircuitBreakerInfo:
    """Circuit breaker information for a database"""
    failure_count: int = 0
    last_failure_time: Optional[datetime] = None
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    last_success_time: Optional[datetime] = None


@dataclass
class DatabaseInfo:
    """Database configuration information"""
    uri: str
    name: str
    pool: Optional[DatabaseConnectionPool] = None
    is_active: bool = True
    size_gb: float = 0.0
    files_count: int = 0
    circuit_breaker: CircuitBreakerInfo = None
    
    def __post_init__(self):
        if self.circuit_breaker is None:
            self.circuit_breaker = CircuitBreakerInfo()


class MultiDatabaseManager:
    """Manager for multiple database connections with automatic failover"""

    _instance: Optional['MultiDatabaseManager'] = None
    _lock = asyncio.Lock()

    def __new__(cls) -> 'MultiDatabaseManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self.databases: List[DatabaseInfo] = []
            self.current_write_db_index: int = 0
            self.size_limit_gb: float = 0.5
            self.auto_switch: bool = True
            self._stats_cache: Dict[str, Any] = {}
            self._stats_cache_time: float = 0
            self._switch_lock = asyncio.Lock()  # Prevent race conditions in database switching
            
            # Circuit breaker configuration from environment variables
            import os
            self.max_failures: int = int(os.environ.get('DATABASE_MAX_FAILURES', '5'))
            self.timeout_duration: timedelta = timedelta(seconds=int(os.environ.get('DATABASE_RECOVERY_TIMEOUT', '300')))
            self.half_open_max_calls: int = int(os.environ.get('DATABASE_HALF_OPEN_CALLS', '3'))

    async def initialize(
        self, 
        uris: List[str], 
        names: List[str],
        size_limit_gb: float = 0.5,
        auto_switch: bool = True
    ) -> None:
        """Initialize multiple database connections"""
        async with self._lock:
            if self.databases:  # Already initialized
                return

            self.size_limit_gb = size_limit_gb
            self.auto_switch = auto_switch

            if len(uris) != len(names):
                raise ValueError("Number of URIs and names must match")

            # Initialize database connections
            for i, (uri, name) in enumerate(zip(uris, names)):
                # FIXED: Create truly separate pool instances by bypassing singleton behavior
                pool = DatabaseConnectionPool.__new__(DatabaseConnectionPool)
                pool.__dict__.clear()  # Clear any singleton state
                pool.__init__()  # Initialize fresh instance
                
                await pool.initialize(uri, name)
                
                db_info = DatabaseInfo(
                    uri=uri,
                    name=name,
                    pool=pool,
                    is_active=True
                )
                
                self.databases.append(db_info)
                logger.info(f"Initialized database {i+1}: {name} ({'Primary' if i == 0 else 'Secondary'})")

            # Update database statistics with circuit breaker protection
            await self._update_database_stats_with_circuit_breaker()
            
            logger.info(f"Multi-database manager initialized with {len(self.databases)} databases")


    async def _handle_all_databases_full(self) -> None:
        """Handle emergency scenario when all databases are at capacity"""
        logger.critical("🚨 CRITICAL: All databases at capacity! Implementing emergency measures...")
        
        # Find the least full database as emergency fallback
        active_dbs = [(i, db) for i, db in enumerate(self.databases) if db.is_active]
        if not active_dbs:
            logger.critical("No active databases available!")
            return
            
        # Use the database with lowest usage as emergency fallback
        least_full_index, least_full_db = min(active_dbs, key=lambda x: x[1].size_gb)
        
        old_index = self.current_write_db_index
        self.current_write_db_index = least_full_index
        
        logger.warning(
            f"Emergency fallback: Using least full database {least_full_index + 1} "
            f"({least_full_db.name}) - {least_full_db.size_gb:.3f}GB / {self.size_limit_gb}GB "
            f"({(least_full_db.size_gb/self.size_limit_gb)*100:.1f}%)"
        )
        
        # Log recommendations for admin
        logger.critical("ADMIN ACTION REQUIRED:")
        logger.critical("1. Add more databases to DATABASE_URIS")  
        logger.critical("2. Increase DATABASE_SIZE_LIMIT_GB if under MongoDB limits")
        logger.critical("3. Consider database cleanup/archiving")
        logger.critical("4. Monitor storage usage closely")

    async def get_write_database(self) -> DatabaseConnectionPool:
        """Get the current database for write operations with thread-safe switching and real-time stats"""
        async with self._switch_lock:  # Prevent race conditions
            # Use real-time stats for accurate switching decisions (force=True)
            await self._update_database_stats_with_circuit_breaker(force=True)
            
            if self.auto_switch and len(self.databases) > 1:
                current_db = self.databases[self.current_write_db_index]
                
                # Check if current database is near limit
                if current_db.size_gb >= self.size_limit_gb:
                    old_index = self.current_write_db_index
                    switched = False
                    
                    # Find next available database
                    for i in range(1, len(self.databases)):
                        next_index = (self.current_write_db_index + i) % len(self.databases)
                        next_db = self.databases[next_index]
                        
                        if next_db.is_active and next_db.size_gb < self.size_limit_gb:
                            self.current_write_db_index = next_index
                            logger.info(f"Database switched: {old_index + 1} ({current_db.name}) -> {next_index + 1} ({next_db.name})")
                            switched = True
                            break
                    
                    if not switched:
                        # All databases are at capacity - handle emergency scenario
                        await self._handle_all_databases_full()
                        
            return self.databases[self.current_write_db_index].pool

    async def get_optimal_write_database(self) -> DatabaseConnectionPool:
        """
        Get the optimal database for write operations using smart selection algorithm
        
        This method evaluates all databases using multiple factors:
        1. Storage usage ratio (lower is better)
        2. Circuit breaker health status  
        3. Connection stability and response time
        4. Current load preference (avoid unnecessary switching)
        5. Geographic/network proximity (future enhancement)
        
        Returns the database with the highest optimization score.
        """
        async with self._switch_lock:
            # Use real-time stats for accurate selection
            await self._update_database_stats_with_circuit_breaker(force=True)
            
            if len(self.databases) <= 1:
                return self.databases[0].pool if self.databases else None
                
            best_score = -1
            best_db_index = self.current_write_db_index
            current_db = self.databases[self.current_write_db_index]
            
            logger.debug("🧠 Smart database selection - evaluating databases:")
            
            for i, db_info in enumerate(self.databases):
                if not db_info.is_active:
                    logger.debug(f"  DB{i+1} ({db_info.name}): INACTIVE - skipped")
                    continue
                    
                # Calculate composite score based on multiple factors
                score = self._calculate_database_score(db_info, i == self.current_write_db_index)
                
                logger.debug(
                    f"  DB{i+1} ({db_info.name}): Score={score:.3f} "
                    f"Usage={db_info.size_gb:.3f}GB({(db_info.size_gb/self.size_limit_gb)*100:.1f}%) "
                    f"Circuit={db_info.circuit_breaker.state.value} "
                    f"Failures={db_info.circuit_breaker.failure_count}"
                )
                
                if score > best_score:
                    best_score = score
                    best_db_index = i
            
            # Switch if a significantly better database is found
            if best_db_index != self.current_write_db_index:
                old_db = self.databases[self.current_write_db_index]
                new_db = self.databases[best_db_index]
                self.current_write_db_index = best_db_index
                
                logger.info(
                    f"🎯 Smart switch: DB{self.current_write_db_index + 1} -> DB{best_db_index + 1} "
                    f"({old_db.name} -> {new_db.name}) - Score improved: {best_score:.3f}"
                )
            else:
                logger.debug(f"🎯 Staying with current DB{self.current_write_db_index + 1} (optimal)")
                
            return self.databases[self.current_write_db_index].pool

    def _calculate_database_score(self, db_info: DatabaseInfo, is_current: bool) -> float:
        """
        Calculate optimization score for a database based on multiple factors
        
        Scoring factors (weighted):
        - Storage usage ratio (40%): Lower usage = higher score
        - Circuit breaker health (30%): Healthy databases get higher scores  
        - Current database bonus (15%): Slight preference to avoid unnecessary switching
        - Connection stability (15%): Based on recent success/failure patterns
        
        Returns: Float score between 0.0 (worst) and 1.0 (best)
        """
        if not db_info.is_active:
            return 0.0
            
        circuit = db_info.circuit_breaker
        
        # Factor 1: Storage usage ratio (40% weight) - Lower usage is better
        usage_ratio = min(db_info.size_gb / self.size_limit_gb, 1.0)
        storage_score = max(0.0, 1.0 - usage_ratio)  # Invert: lower usage = higher score
        
        # Apply penalty for databases near capacity (>90%)
        if usage_ratio > 0.9:
            storage_score *= 0.3  # Heavy penalty for near-full databases
        elif usage_ratio > 0.8:
            storage_score *= 0.7  # Moderate penalty for mostly-full databases
            
        # Factor 2: Circuit breaker health (30% weight)
        if circuit.state == CircuitBreakerState.CLOSED:
            # Healthy database - score based on failure history
            if circuit.failure_count == 0:
                health_score = 1.0  # Perfect health
            else:
                # Gradual decrease based on recent failures
                health_score = max(0.3, 1.0 - (circuit.failure_count / self.max_failures) * 0.7)
        elif circuit.state == CircuitBreakerState.HALF_OPEN:
            health_score = 0.5  # Testing recovery - moderate score
        else:  # OPEN
            health_score = 0.0  # Circuit open - unusable
            
        # Factor 3: Current database bonus (15% weight) - Avoid unnecessary switching
        current_bonus = 0.15 if is_current else 0.0
        
        # Factor 4: Connection stability (15% weight) - Based on success/failure ratio
        stability_score = 0.8  # Default decent stability
        
        if circuit.last_success_time and circuit.last_failure_time:
            # Recent activity - calculate stability based on time since last events
            from datetime import datetime
            now = datetime.now()
            
            time_since_success = (now - circuit.last_success_time).total_seconds()
            time_since_failure = (now - circuit.last_failure_time).total_seconds()
            
            if time_since_failure < time_since_success:
                # More recent failure than success - lower stability
                stability_score = max(0.2, stability_score - 0.4)
            else:
                # More recent success - higher stability
                stability_score = min(1.0, stability_score + 0.2)
        elif circuit.last_success_time:
            # Only successes recorded - high stability
            stability_score = 1.0
        elif circuit.last_failure_time:
            # Only failures recorded - low stability  
            stability_score = 0.3
            
        # Calculate weighted composite score
        composite_score = (
            storage_score * 0.40 +      # 40% weight on storage usage
            health_score * 0.30 +       # 30% weight on circuit breaker health
            stability_score * 0.15 +    # 15% weight on connection stability  
            current_bonus               # 15% weight on current database preference
        )
        
        # Apply additional modifiers
        
        # Boost score for databases with very low usage (<25%)
        if usage_ratio < 0.25:
            composite_score = min(1.0, composite_score + 0.1)
            
        # Penalize databases that are unusable due to circuit breaker
        if circuit.state == CircuitBreakerState.OPEN:
            composite_score = 0.0
            
        return round(composite_score, 3)

    async def get_all_databases(self) -> List[DatabaseConnectionPool]:
        """Get all active database pools"""
        return [db.pool for db in self.databases if db.is_active and db.pool]

    async def get_database_by_index(self, index: int) -> Optional[DatabaseConnectionPool]:
        """Get database by index"""
        if 0 <= index < len(self.databases) and self.databases[index].is_active:
            return self.databases[index].pool
        return None

    async def get_collection_from_all(self, collection_name: str) -> List[AsyncIOMotorCollection]:
        """Get collection from all active databases"""
        collections = []
        for db_info in self.databases:
            if db_info.is_active and db_info.pool:
                try:
                    collection = await db_info.pool.get_collection(collection_name)
                    collections.append(collection)
                except Exception as e:
                    logger.error(f"Error getting collection from {db_info.name}: {e}")
                    db_info.is_active = False
        return collections

    async def find_file_in_all_databases(
        self, 
        collection_name: str, 
        query: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
        """
        Find a file in all databases with circuit breaker protection
        Returns: (document, database_index) or (None, None)
        """
        for i, db_info in enumerate(self.databases):
            if not db_info.is_active or not db_info.pool:
                continue
                
            try:
                # Use circuit breaker for find operations
                async def find_operation():
                    collection = await db_info.pool.get_collection(collection_name)
                    return await collection.find_one(query)
                
                document = await self._execute_with_circuit_breaker(
                    db_info, "find_file", find_operation
                )
                if document:
                    return document, i
            except Exception as e:
                logger.error(f"Error searching in database {db_info.name}: {e}")
                # Circuit breaker will handle marking database as inactive
                
        return None, None

    async def count_across_all_databases(
        self, 
        collection_name: str, 
        query: Dict[str, Any]
    ) -> int:
        """Count documents across all databases"""
        total_count = 0
        
        tasks = []
        for db_info in self.databases:
            if db_info.is_active and db_info.pool:
                task = self._count_in_database(db_info, collection_name, query)
                tasks.append(task)
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, int):
                    total_count += result
                elif isinstance(result, Exception):
                    logger.error(f"Error counting documents: {result}")
        
        return total_count

    async def _count_in_database(
        self, 
        db_info: DatabaseInfo, 
        collection_name: str, 
        query: Dict[str, Any]
    ) -> int:
        """Count documents in a specific database with circuit breaker protection"""
        try:
            # Use circuit breaker for count operations
            async def count_operation():
                collection = await db_info.pool.get_collection(collection_name)
                return await collection.count_documents(query)
            
            return await self._execute_with_circuit_breaker(
                db_info, "count_documents", count_operation
            )
        except Exception as e:
            logger.error(f"Error counting in database {db_info.name}: {e}")
            # Circuit breaker will handle marking database as inactive
            return 0

    async def search_across_all_databases(
        self, 
        collection_name: str, 
        query: Dict[str, Any], 
        limit: int = 10, 
        skip: int = 0,
        sort: Optional[List[Tuple[str, int]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search across all databases and return properly paginated combined results
        
        FIXED: This method now correctly handles cross-database pagination by:
        1. Getting ALL matching results from each database first
        2. Combining and sorting ALL results together  
        3. THEN applying skip/limit to the final sorted list
        """
        all_results = []
        
        # Get ALL matching results from each database (no individual limits)
        tasks = []
        for db_info in self.databases:
            if db_info.is_active and db_info.pool:
                # Get all matching results from this database (for proper sorting)
                task = self._get_all_matching_from_database(db_info, collection_name, query, sort)
                tasks.append(task)
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    all_results.extend(result)
                elif isinstance(result, Exception):
                    logger.error(f"Error searching databases: {result}")
        
        # Sort the COMBINED results properly
        if sort and all_results:
            for sort_field, sort_direction in reversed(sort):
                all_results.sort(
                    key=lambda x: x.get(sort_field, 0), 
                    reverse=(sort_direction == -1)
                )
        
        # NOW apply pagination to the final sorted results  
        return all_results[skip:skip + limit]

    async def _get_all_matching_from_database(
        self, 
        db_info: DatabaseInfo, 
        collection_name: str, 
        query: Dict[str, Any],
        sort: Optional[List[Tuple[str, int]]] = None
    ) -> List[Dict[str, Any]]:
        """Get ALL matching results from a specific database (no limit for proper cross-DB sorting)"""
        try:
            collection = await db_info.pool.get_collection(collection_name)
            cursor = collection.find(query)
            
            if sort:
                cursor = cursor.sort(sort)
                
            # Get ALL matching results (no limit) for proper cross-database sorting
            # We'll apply the overall limit after combining all results
            return await cursor.to_list(length=None)
            
        except Exception as e:
            logger.error(f"Error getting all matching from database {db_info.name}: {e}")
            db_info.is_active = False
            return []


    async def get_database_stats(self) -> List[Dict[str, Any]]:
        """Get statistics for all databases with circuit breaker protection"""
        await self._update_database_stats_with_circuit_breaker()
        
        stats = []
        for i, db_info in enumerate(self.databases):
            stats.append({
                'index': i,
                'name': db_info.name,
                'is_active': db_info.is_active,
                'is_current_write': i == self.current_write_db_index,
                'size_gb': round(db_info.size_gb, 3),
                'size_limit_gb': self.size_limit_gb,
                'files_count': db_info.files_count,
                'usage_percentage': round((db_info.size_gb / self.size_limit_gb) * 100, 1) if self.size_limit_gb > 0 else 0
            })
        
        return stats

    async def set_write_database(self, index: int) -> bool:
        """Manually set the write database with thread-safe locking"""
        async with self._switch_lock:  # Ensure thread safety
            if 0 <= index < len(self.databases) and self.databases[index].is_active:
                old_index = self.current_write_db_index
                self.current_write_db_index = index
                logger.info(f"Write database manually switched from {old_index + 1} to {index + 1}")
                return True
            return False

    def _check_circuit_breaker(self, db_info: DatabaseInfo) -> bool:
        """
        Check if circuit breaker allows operation for this database
        Returns: True if operation is allowed, False if circuit is OPEN
        """
        circuit = db_info.circuit_breaker
        now = datetime.now()
        
        if circuit.state == CircuitBreakerState.OPEN:
            # Check if timeout has expired
            if circuit.last_failure_time and (now - circuit.last_failure_time) >= self.timeout_duration:
                circuit.state = CircuitBreakerState.HALF_OPEN
                logger.info(f"Circuit breaker for {db_info.name} moved to HALF_OPEN (testing recovery)")
                return True
            else:
                # Circuit is still open, reject the request
                return False
                
        elif circuit.state == CircuitBreakerState.HALF_OPEN:
            # In half-open, allow limited calls to test recovery
            return True
            
        else:  # CLOSED
            # Normal operation
            return True

    def _record_success(self, db_info: DatabaseInfo) -> None:
        """Record a successful operation"""
        circuit = db_info.circuit_breaker
        circuit.last_success_time = datetime.now()
        
        if circuit.state == CircuitBreakerState.HALF_OPEN:
            # Success in HALF_OPEN state, reset circuit breaker
            circuit.state = CircuitBreakerState.CLOSED
            circuit.failure_count = 0
            logger.info(f"Circuit breaker for {db_info.name} CLOSED (recovery successful)")
        elif circuit.state == CircuitBreakerState.CLOSED:
            # Reset failure count on successful operation
            circuit.failure_count = 0

    def _record_failure(self, db_info: DatabaseInfo, error: Exception) -> None:
        """Record a failed operation and update circuit breaker state"""
        circuit = db_info.circuit_breaker
        circuit.failure_count += 1
        circuit.last_failure_time = datetime.now()
        
        if circuit.failure_count >= self.max_failures:
            if circuit.state != CircuitBreakerState.OPEN:
                circuit.state = CircuitBreakerState.OPEN
                db_info.is_active = False  # Mark database as inactive
                logger.error(
                    f"🔴 Circuit breaker OPENED for database {db_info.name} "
                    f"after {circuit.failure_count} failures. Last error: {error}"
                )
        else:
            logger.warning(
                f"Database {db_info.name} failure {circuit.failure_count}/{self.max_failures}: {error}"
            )

    async def _execute_with_circuit_breaker(self, db_info: DatabaseInfo, _operation_name: str, operation) -> Any:
        """
        Execute database operation with circuit breaker protection
        
        Args:
            db_info: Database information
            _operation_name: Name of the operation for logging (currently unused)
            operation: Async callable to execute
            
        Returns: Operation result
        Raises: Exception if circuit is OPEN or operation fails
        """
        # Check if circuit breaker allows this operation
        if not self._check_circuit_breaker(db_info):
            raise Exception(f"Circuit breaker OPEN for database {db_info.name}")
            
        try:
            # Execute the operation
            result = await operation()
            
            # Record success
            self._record_success(db_info)
            
            return result
            
        except Exception as e:
            # Record failure and update circuit breaker
            self._record_failure(db_info, e)
            raise e

    async def _update_database_stats_with_circuit_breaker(self, force: bool = False) -> None:
        """Update database statistics with circuit breaker protection and real-time updates"""
        current_time = asyncio.get_event_loop().time()
        
        # For write operations, always use fresh stats (force=True)
        # For read operations, use shorter cache (30 seconds vs 5 minutes)
        cache_duration = 0 if force else 30
        
        if not force and current_time - self._stats_cache_time < cache_duration:
            return

        for db_info in self.databases:
            if not db_info.pool:
                continue
                
            try:
                # Use circuit breaker for stats operations
                async def get_stats():
                    stats = await db_info.pool.database.command("dbStats")
                    collection = await db_info.pool.get_collection("media_files")
                    files_count = await collection.count_documents({})
                    return stats, files_count
                
                stats, files_count = await self._execute_with_circuit_breaker(
                    db_info, "get_stats", get_stats
                )
                
                # Update database info
                db_info.size_gb = stats.get('dataSize', 0) / (1024 ** 3)  # Convert to GB
                db_info.files_count = files_count
                
                # If database was inactive due to circuit breaker, mark as active
                if not db_info.is_active and db_info.circuit_breaker.state == CircuitBreakerState.CLOSED:
                    db_info.is_active = True
                    logger.info(f"Database {db_info.name} marked as active (circuit breaker closed)")
                
                logger.debug(f"Database {db_info.name}: {db_info.size_gb:.3f}GB, {db_info.files_count} files")
                
            except Exception as e:
                # Circuit breaker will handle marking database as inactive
                logger.debug(f"Failed to update stats for database {db_info.name}: {e}")

        self._stats_cache_time = current_time

    async def close(self) -> None:
        """Close all database connections"""
        for db_info in self.databases:
            if db_info.pool:
                try:
                    await db_info.pool.close()
                except Exception as e:
                    logger.error(f"Error closing database {db_info.name}: {e}")
        
        self.databases.clear()
        logger.info("Multi-database manager closed")

    @property
    def is_multi_database(self) -> bool:
        """Check if multiple databases are configured"""
        return len(self.databases) > 1

# Global instance
multi_db_pool = MultiDatabaseManager()