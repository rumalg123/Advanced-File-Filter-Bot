"""
Vulture whitelist for intentionally "unused" code
These symbols are used by frameworks or are intentional API surface
"""

# aiohttp handler parameters (required by framework)
request = None  # Used in aiohttp route handlers

# PyroFork handler parameters (required by framework)
client = None
message = None
callback_query = None

# Dataclass fields that might not be directly accessed
file_ref = None
file_unique_id = None
correlation_id = None

# Command handler method names (used via introspection)
start_command = None
help_command = None
stats_command = None

# Async context manager methods
__aenter__ = None
__aexit__ = None