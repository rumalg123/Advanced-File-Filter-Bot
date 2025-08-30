from datetime import datetime
from typing import Dict, List

from core.cache.redis_cache import CacheManager
from core.utils.logger import get_logger

logger = get_logger(__name__)


class CacheMonitor:
    """Monitor and debug cache usage"""

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager

    async def get_cache_stats(self) -> Dict[str, any]:
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
                    "total_keys": info.get('db0', {}).get('keys', 0),
                    "expires": info.get('db0', {}).get('expires', 0),
                    "by_pattern": key_counts
                },
                "server": {
                    "redis_version": info.get('redis_version', 'N/A'),
                    "uptime_in_days": info.get('uptime_in_days', 0),
                    "connected_clients": info.get('connected_clients', 0),
                }
            }
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {"error": str(e)}

    async def _count_keys_by_pattern(self) -> Dict[str, int]:
        """Count keys by pattern"""
        patterns = {
            "media_files": "media:*",
            "users": "user:*",
            "connections": "connections:*",
            "active_channels": "active_channels_list",
            "filters": "filter:*",
            "filter_lists": "filters_list:*",
            "search_results": "search:*",
            "rate_limits": "rate_limit:*",
            "bot_settings": "bot_setting:*",
            "sessions": "*session*"
        }

        counts = {}
        for name, pattern in patterns.items():
            count = 0
            async for _ in self.cache.redis.scan_iter(match=pattern):
                count += 1
            counts[name] = count

        return counts

    async def find_duplicate_data(self) -> List[Dict[str, any]]:
        """Find potential duplicate cached data"""
        duplicates = []

        # Check for media files with multiple cache entries
        media_keys = []
        async for key in self.cache.redis.scan_iter(match="media:*"):
            media_keys.append(key.decode())

        # Group by potential duplicates
        file_cache_map = {}  # file_id -> list of cache keys

        for key in media_keys:
            data = await self.cache.get(key.replace("media:", ""))
            if data and isinstance(data, dict):
                file_id = data.get('file_id') or data.get('_id')
                if file_id:
                    if file_id not in file_cache_map:
                        file_cache_map[file_id] = []
                    file_cache_map[file_id].append(key)

        # Find files with multiple cache entries
        for file_id, keys in file_cache_map.items():
            if len(keys) > 1:
                duplicates.append({
                    "type": "media_file",
                    "file_id": file_id,
                    "cache_keys": keys,
                    "count": len(keys)
                })

        return duplicates

    async def analyze_cache_usage(self, sample_size: int = 100) -> Dict[str, any]:
        """Analyze cache usage patterns"""
        analysis = {
            "large_values": [],
            "expired_soon": [],
            "no_ttl": [],
            "key_size_distribution": {}
        }

        # Sample keys
        sampled = 0
        async for key in self.cache.redis.scan_iter(count=sample_size):
            if sampled >= sample_size:
                break

            key_str = key.decode()

            try:
                # Get value size (some Redis versions might not support memory_usage)
                try:
                    value_size = await self.cache.redis.memory_usage(key)
                except (AttributeError, Exception):
                    # Fallback: estimate size by getting the actual value
                    value = await self.cache.redis.get(key)
                    value_size = len(str(value)) if value else 0

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

    async def get_slow_commands(self) -> List[Dict[str, any]]:
        """Get slow Redis commands"""
        try:
            slow_log = await self.cache.redis.slowlog_get(10)

            slow_commands = []
            for entry in slow_log:
                slow_commands.append({
                    "id": entry['id'],
                    "timestamp": datetime.fromtimestamp(entry['start_time']).isoformat(),
                    "duration_microseconds": entry['duration'],
                    "command": ' '.join(entry['command'][:3]) + ('...' if len(entry['command']) > 3 else ''),
                })

            return slow_commands
        except Exception as e:
            logger.error(f"Error getting slow commands: {e}")
            return []

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