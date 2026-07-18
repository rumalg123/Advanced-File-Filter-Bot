from typing import Dict, List, Any

from core.cache.config import CacheKeyGenerator, CachePatterns
from core.cache.redis_cache import CacheManager
from core.cache.serialization import get_serialization_stats, estimate_memory_usage
from core.utils.logger import get_logger

logger = get_logger(__name__)


class CacheMonitor:
    """Monitor and debug cache usage"""

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager

    @staticmethod
    def _key_text(key: Any) -> str:
        return key.decode('utf-8', errors='replace') if isinstance(key, bytes) else str(key)

    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics"""
        if not self.cache.redis:
            return {"error": "Redis not connected"}

        try:
            # Get Redis info
            info = await self.cache.redis.info()

            # Get memory info
            memory_info = await self.cache.redis.info("memory")

            # Count keys by pattern
            key_counts = await self._count_keys_by_pattern()

            # Get cache hit rate
            hits = info.get('keyspace_hits', 0)
            misses = info.get('keyspace_misses', 0)
            total_ops = hits + misses
            hit_rate = (hits / total_ops * 100) if total_ops > 0 else 0

            # Get serialization stats
            serialization_stats = get_serialization_stats()

            database_number = int(
                self.cache.redis.connection_pool.connection_kwargs.get('db', 0) or 0
            )
            keyspace = info.get(f'db{database_number}', {})

            return {
                "status": "connected",
                "memory": {
                    "used_memory_human": memory_info.get('used_memory_human', 'N/A'),
                    "used_memory_rss_human": memory_info.get('used_memory_rss_human', 'N/A'),
                    "used_memory_peak_human": memory_info.get('used_memory_peak_human', 'N/A'),
                    "mem_fragmentation_ratio": memory_info.get('mem_fragmentation_ratio', 'N/A'),
                },
                "performance": {
                    "total_commands_processed": info.get('total_commands_processed', 0),
                    "instantaneous_ops_per_sec": info.get('instantaneous_ops_per_sec', 0),
                    "cache_hit_rate": f"{hit_rate:.2f}%",
                    "keyspace_hits": hits,
                    "keyspace_misses": misses,
                },
                "keys": {
                    "database": database_number,
                    "total_keys": keyspace.get('keys', 0),
                    "expires": keyspace.get('expires', 0),
                    "by_pattern": key_counts
                },
                "server": {
                    "redis_version": info.get('redis_version', 'N/A'),
                    "uptime_in_days": info.get('uptime_in_days', 0),
                    "connected_clients": info.get('connected_clients', 0),
                },
                "serialization": serialization_stats
            }
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {"error": str(e)}

    async def _count_keys_by_pattern(self) -> Dict[str, int]:
        """Count keys by pattern"""
        patterns = {
            "media_files": CachePatterns.ALL_MEDIA,
            "users": CachePatterns.ALL_USERS,
            "connections": CachePatterns.ALL_CONNECTIONS,
            "active_channels": CacheKeyGenerator.active_channels(),
            "filters": CachePatterns.ALL_FILTERS,
            "filter_lists": CachePatterns.ALL_FILTER_LISTS,
            "search_results": CachePatterns.ALL_SEARCH_CACHE,
            "delivery_sessions": CachePatterns.ALL_SEARCH_RESULTS,
            "rate_limits": CachePatterns.ALL_RATE_LIMITS,
            "bot_settings": CachePatterns.ALL_BOT_SETTINGS,
            "sessions": CachePatterns.ANY_SESSION
        }

        counts = {}
        for name, pattern in patterns.items():
            count = 0
            async for _ in self.cache.redis.scan_iter(match=pattern):
                count += 1
            counts[name] = count

        return counts

    async def find_duplicate_data(self) -> List[Dict[str, Any]]:
        """Classify intentional media aliases and identify only stale aliases."""
        if not self.cache.redis:
            return []

        media_keys: List[str] = []
        async for key in self.cache.redis.scan_iter(match=CachePatterns.ALL_MEDIA):
            media_keys.append(self._key_text(key))

        file_cache_map: Dict[str, Dict[str, Any]] = {}

        for key in media_keys:
            data = await self.cache.get(key)
            if data and isinstance(data, dict):
                canonical_id = data.get('file_unique_id') or data.get('_id') or data.get('file_id')
                if canonical_id is None:
                    continue
                group = file_cache_map.setdefault(str(canonical_id), {
                    'cache_keys': [],
                    'valid_cache_keys': set(),
                })
                group['cache_keys'].append(key)
                for field in ('file_unique_id', '_id', 'file_id', 'file_ref'):
                    identifier = data.get(field)
                    if identifier:
                        group['valid_cache_keys'].add(CacheKeyGenerator.media(str(identifier)))

        aliases = []
        for file_id, group in file_cache_map.items():
            cache_keys = list(dict.fromkeys(group['cache_keys']))
            valid_keys = group['valid_cache_keys']
            stale_keys = [key for key in cache_keys if key not in valid_keys]
            if len(cache_keys) > 1 or stale_keys:
                aliases.append({
                    "type": "media_alias_group",
                    "file_id": file_id,
                    "cache_keys": cache_keys,
                    "valid_cache_keys": sorted(key for key in cache_keys if key in valid_keys),
                    "stale_cache_keys": stale_keys,
                    "count": len(cache_keys),
                })

        return aliases

    async def analyze_cache_usage(self, sample_size: int = 100) -> Dict[str, Any]:
        """Analyze cache usage patterns"""
        analysis = {
            "large_values": [],
            "expired_soon": [],
            "no_ttl": [],
            "key_size_distribution": {}
        }
        if not self.cache.redis:
            analysis['error'] = 'Redis not connected'
            return analysis

        # Sample keys
        sampled = 0
        async for key in self.cache.redis.scan_iter(count=sample_size):
            if sampled >= sample_size:
                break

            key_str = self._key_text(key)

            try:
                # Get value size (some Redis versions might not support memory_usage)
                try:
                    value_size = await self.cache.redis.memory_usage(key)
                except Exception:
                    # Fallback: estimate size by getting the actual value
                    value = await self.cache.redis.get(key)
                    value_size = len(value) if value else 0

                # Get TTL
                ttl = await self.cache.redis.ttl(key)

                # Categorize by size
                if value_size:
                    if value_size > 10240:  # > 10KB
                        analysis["large_values"].append({
                            "key": key_str,
                            "size_bytes": value_size,
                            "size_human": self._format_bytes(value_size)
                        })

                    # Size distribution
                    size_category = self._get_size_category(value_size)
                    analysis["key_size_distribution"][size_category] = \
                        analysis["key_size_distribution"].get(size_category, 0) + 1

                # Check TTL
                if ttl == -1:  # No expiration
                    analysis["no_ttl"].append(key_str)
                elif 0 < ttl < 60:  # Expires in less than 1 minute
                    analysis["expired_soon"].append({
                        "key": key_str,
                        "ttl_seconds": ttl
                    })

                sampled += 1

            except Exception as e:
                logger.debug(f"Error analyzing key {key_str}: {e}")

        return analysis

    async def analyze_serialization_efficiency(self, sample_size: int = 20) -> Dict[str, Any]:
        """Analyze serialization efficiency for cached data"""
        if not self.cache.redis:
            return {"error": "Redis not connected"}

        analysis: Dict[str, Any] = {
            "samples_analyzed": 0,
            "total_current_size": 0,
            "potential_savings": {},
            "method_comparison": [],
            "recommendations": []
        }

        try:
            sampled = 0
            async for key in self.cache.redis.scan_iter(count=sample_size * 2):
                if sampled >= sample_size:
                    break

                try:
                    # Get the cached value
                    key_text = self._key_text(key)
                    value = await self.cache.get(key_text)
                    if value is None or not isinstance(value, (dict, list)):
                        continue

                    # Get current stored size
                    raw_value = await self.cache.redis.get(key)
                    current_size = len(raw_value) if raw_value else 0

                    # Estimate sizes with different methods
                    estimates = estimate_memory_usage(value)

                    if estimates and current_size > 0:
                        analysis["samples_analyzed"] += 1
                        analysis["total_current_size"] += current_size

                        # Find best method
                        best_method = min(estimates, key=estimates.get)
                        best_size = estimates[best_method]

                        if best_size < current_size:
                            analysis["method_comparison"].append({
                                "key": key_text[:40],
                                "current_size": current_size,
                                "best_method": best_method,
                                "best_size": best_size,
                                "savings_percent": round((1 - best_size / current_size) * 100, 1)
                            })

                    sampled += 1

                except Exception as e:
                    logger.debug(f"Error analyzing key serialization: {e}")

            # Calculate potential savings by method
            if analysis["method_comparison"]:
                total_savings = sum(
                    item["current_size"] - item["best_size"]
                    for item in analysis["method_comparison"]
                )
                analysis["potential_savings"] = {
                    "bytes": total_savings,
                    "human": self._format_bytes(total_savings),
                    "percent": round(total_savings / analysis["total_current_size"] * 100, 1)
                    if analysis["total_current_size"] > 0 else 0
                }

                # Add recommendations
                if analysis["potential_savings"]["percent"] > 10:
                    analysis["recommendations"].append(
                        "Consider enabling compressed serialization for large values"
                    )

        except Exception as e:
            logger.error(f"Error analyzing serialization efficiency: {e}")
            analysis["error"] = str(e)

        return analysis

    @staticmethod
    def _format_bytes(bytes_val: int) -> str:
        """Format bytes to human readable"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_val < 1024:
                return f"{bytes_val:.2f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.2f} TB"

    @staticmethod
    def _get_size_category(size: int) -> str:
        """Categorize key size"""
        if size < 1024:
            return "< 1KB"
        elif size < 10240:
            return "1KB - 10KB"
        elif size < 102400:
            return "10KB - 100KB"
        elif size < 1048576:
            return "100KB - 1MB"
        else:
            return "> 1MB"
