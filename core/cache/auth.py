"""Optional Redis ACL credentials from mounted files, never from logging.

No production authentication changes unless REDIS_PASSWORD_FILE (or
REDIS_STATE_PASSWORD_FILE) is explicitly configured.
"""
from pathlib import Path
from urllib.parse import urlsplit


def redis_auth_kwargs(uri: str, *, username: str = "", password_file: str = "") -> dict:
    """Return redis-py connection kwargs, reading only explicitly configured files.

    A URI-embedded password remains supported for legacy deployments, but
    combining two credential sources is rejected rather than silently selecting
    one. No password, URI or file content appears in exception messages.
    """
    if not username and not password_file:
        return {}

    parsed = urlsplit(uri)
    if parsed.username or parsed.password:
        raise ValueError("Redis URI credentials cannot be mixed with file-based ACL settings")
    if username and not password_file:
        raise ValueError("REDIS_USERNAME requires REDIS_PASSWORD_FILE")
    if not password_file:
        return {}

    path = Path(password_file)
    if not path.is_absolute():
        raise ValueError("Redis password file must be an absolute path")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError("Redis password file cannot be read") from None
    if not 16 <= len(data) <= 4096:
        raise ValueError("Redis password file must contain a strong, bounded credential")
    try:
        password = data.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError:
        raise ValueError("Redis password file encoding is invalid") from None
    if len(password) < 16 or "\n" in password or "\r" in password:
        raise ValueError("Redis password file contains an invalid credential")
    return {"password": password, **({"username": username} if username else {})}
