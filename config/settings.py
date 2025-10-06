"""
Centralized configuration management using Pydantic Settings
Follows 12-factor app principles with environment variable overrides
"""

import os
from typing import List, Optional, Any
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Import moved to avoid circular dependency
# from core.utils import default_messages


class TelegramConfig(BaseSettings):
    """Telegram API configuration"""
    
    model_config = SettingsConfigDict(
        env_prefix='',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Core Telegram API credentials
    api_id: int = Field(default=0, description="Telegram API ID")
    api_hash: str = Field(default='', description="Telegram API hash")
    bot_token: str = Field(default='', description="Bot token from BotFather")
    session: str = Field(default='Media_search', description="Session name")
    
    @field_validator('api_id')
    def validate_api_id(cls, v):
        if v == 0:
            raise ValueError("API_ID is required")
        return v
    
    @field_validator('api_hash', 'bot_token')
    def validate_required_strings(cls, v, info):
        if not v:
            raise ValueError(f"{info.field_name.upper()} is required")
        return v


class DatabaseConfig(BaseSettings):
    """Database configuration"""
    
    model_config = SettingsConfigDict(
        env_prefix='DATABASE_',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Primary database
    uri: str = Field(default='', description="Primary MongoDB URI")
    name: str = Field(default='PIRO', description="Primary database name")
    collection_name: str = Field(default='FILES', env='COLLECTION_NAME', description="Collection name")
    
    # Multi-database support
    size_limit_gb: float = Field(default=0.5, description="Database size limit in GB")
    auto_switch: bool = Field(default=True, description="Enable automatic database switching")
    uris: str = Field(default='', description="Additional database URIs (comma-separated)")
    names: str = Field(default='', description="Additional database names (comma-separated)")
    
    # Circuit breaker configuration
    max_failures: int = Field(default=5, description="Max failures before circuit breaker opens")
    recovery_timeout: int = Field(default=300, description="Recovery timeout in seconds")
    half_open_calls: int = Field(default=3, description="Max calls in half-open state")
    
    @field_validator('uri')
    def validate_uri(cls, v):
        if not v:
            raise ValueError("DATABASE_URI is required")
        return v
    
    def get_additional_uris(self) -> List[str]:
        """Parse additional database URIs"""
        return [uri.strip() for uri in self.uris.split(',') if uri.strip()]
    
    def get_additional_names(self) -> List[str]:
        """Parse additional database names"""
        return [name.strip() for name in self.names.split(',') if name.strip()]


class RedisConfig(BaseSettings):
    """Redis configuration"""
    
    model_config = SettingsConfigDict(
        env_prefix='REDIS_',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    uri: str = Field(default='', description="Redis connection URI")
    
    @field_validator('uri')
    def validate_uri(cls, v):
        if not v:
            raise ValueError("REDIS_URI is required")
        return v


class ServerConfig(BaseSettings):
    """Server configuration"""
    
    model_config = SettingsConfigDict(
        env_prefix='',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    port: int = Field(default=8000, description="Server port")
    workers: int = Field(default=50, description="Number of workers")
    
    @field_validator('port')
    def validate_port(cls, v):
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v


class FeatureConfig(BaseSettings):
    """Feature flags and toggles"""
    
    model_config = SettingsConfigDict(
        env_prefix='',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Feature toggles
    use_caption_filter: bool = Field(default=True, description="Enable caption filtering")
    disable_premium: bool = Field(default=True, description="Disable premium features")
    disable_filter: bool = Field(default=False, description="Disable filtering entirely")
    public_file_store: bool = Field(default=False, description="Enable public file store")
    keep_original_caption: bool = Field(default=True, description="Keep original file captions")
    use_original_caption_for_batch: bool = Field(default=True, description="Use original captions in batch mode")
    
    # Premium system
    premium_duration_days: int = Field(default=30, description="Premium subscription duration in days")
    non_premium_daily_limit: int = Field(default=10, description="Daily file limit for free users")
    premium_price: str = Field(default="$1", description="Premium subscription price with currency")
    
    # Timeouts and limits
    message_delete_seconds: int = Field(default=300, description="Auto-delete timeout in seconds")
    max_btn_size: int = Field(default=12, description="Maximum button size")
    request_per_day: int = Field(default=3, description="Requests per day limit")
    request_warning_limit: int = Field(default=5, description="Warning limit for requests")


class ChannelConfig(BaseSettings):
    """Channel and group configuration"""
    
    model_config = SettingsConfigDict(
        env_prefix='',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Channels and groups
    log_channel: int = Field(default=0, description="Log channel ID")
    index_req_channel: int = Field(default=0, description="Index request channel ID")
    file_store_channel: str = Field(default='', description="File store channel")
    delete_channel: Optional[int] = Field(default=None, description="Delete channel ID")
    req_channel: int = Field(default=0, description="Request channel ID")
    support_group_id: Optional[int] = Field(default=None, description="Support group ID")
    
    # Auth configuration
    auth_channel: Optional[str] = Field(default=None, description="Auth channel")
    auth_groups: str = Field(default='', description="Auth groups (comma-separated)")
    auth_users: str = Field(default='', description="Auth users (comma-separated)")
    
    # Channel lists
    admins: str = Field(default='', description="Admin user IDs (comma-separated)")
    channels: str = Field(default='0', description="Channel IDs (comma-separated)")
    pics: str = Field(default='', description="Picture URLs (comma-separated)")
    
    @field_validator('channels', 'admins', 'pics', 'auth_groups', 'auth_users')
    def validate_comma_separated(cls, v, info):
        """Handle empty strings and normalize comma-separated values"""
        if v is None or v == '':
            # Return appropriate defaults for each field
            field_defaults = {
                'channels': '0',
                'admins': '',
                'pics': '',
                'auth_groups': '',
                'auth_users': ''
            }
            return field_defaults.get(info.field_name, '')
        return str(v).strip()
    
    @model_validator(mode='before')
    def set_default_channels(cls, values):
        """Set default values for channels based on log_channel"""
        if isinstance(values, dict):
            log_channel = values.get('log_channel', 0)
            if values.get('index_req_channel', 0) == 0:
                values['index_req_channel'] = log_channel
            if values.get('req_channel', 0) == 0:
                values['req_channel'] = log_channel
        return values
    
    def get_admin_list(self) -> List[int]:
        """Parse admin IDs"""
        return [int(x.strip()) for x in self.admins.split(',') if x.strip().isdigit()]
    
    def get_channel_list(self) -> List[int]:
        """Parse channel IDs"""
        return [int(x.strip()) for x in self.channels.split(',') if x.strip().isdigit()]
    
    def get_pics_list(self) -> List[str]:
        """Parse picture URLs"""
        return [pic.strip() for pic in self.pics.split(',') if pic.strip()]
    
    def get_auth_groups_list(self) -> List[int]:
        """Parse auth group IDs"""
        return [int(x.strip()) for x in self.auth_groups.split(',') if x.strip().lstrip('-').isdigit()]
    
    def get_auth_users_list(self) -> List[int]:
        """Parse auth user IDs"""
        return [int(x.strip()) for x in self.auth_users.split(',') if x.strip().isdigit()]


class MessageConfig(BaseSettings):
    """Message templates and content"""
    
    model_config = SettingsConfigDict(
        env_prefix='',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    # Custom captions
    custom_file_caption: str = Field(default='', description="Custom file caption template")
    batch_file_caption: str = Field(default='', description="Batch file caption template")
    
    # Messages (using string literals to avoid circular import)
    auto_delete_message: str = Field(
        default="⏰ This {content_type} will be automatically deleted in {minutes} minutes to save disk space. Please forward it to your personal chat to keep it.", 
        description="Auto-delete message template"
    )
    start_message: str = Field(
        default="👋 Hello! I'm a file search bot. Send me any file name and I'll try to find it for you.",
        description="Start command message template"
    )
    
    # Support configuration
    support_group_url: str = Field(default='', description="Support group URL")
    support_group_name: str = Field(default='Support Group', description="Support group name")
    payment_link: str = Field(
        default='https://buymeacoffee.com/matthewmurdock001',
        description="Payment link"
    )


class UpdateConfig(BaseSettings):
    """Auto-update configuration"""
    
    model_config = SettingsConfigDict(
        env_prefix='UPDATE_',
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )
    
    repo: str = Field(
        default="https://github.com/rumalg123/Advanced-File-Filter-Bot.git",
        description="Update repository URL"
    )
    branch: str = Field(default="main", description="Update branch")


class Settings:
    """Main application settings"""
    
    def __init__(self):
        """Initialize all sub-configurations"""
        # Initialize sub-configurations directly to avoid nested Pydantic JSON parsing issues
        self.telegram = TelegramConfig()
        self.database = DatabaseConfig()
        self.redis = RedisConfig()
        self.server = ServerConfig()
        self.features = FeatureConfig()
        self.channels = ChannelConfig()
        self.messages = MessageConfig()
        self.updates = UpdateConfig()
    
    # Environment detection
    @property
    def is_development(self) -> bool:
        """Check if running in development mode"""
        return os.getenv('ENVIRONMENT', 'production').lower() in ('dev', 'development')
    
    @property
    def is_production(self) -> bool:
        """Check if running in production mode"""
        return not self.is_development
    
    @property
    def is_docker(self) -> bool:
        """Check if running in Docker"""
        return bool(os.getenv("IN_DOCKER")) or os.path.exists('/.dockerenv')
    
    @property
    def is_kubernetes(self) -> bool:
        """Check if running in Kubernetes"""
        return bool(os.getenv("KUBERNETES_SERVICE_HOST"))
    
    def get_concurrency_limits(self) -> dict:
        """Get concurrency limits from environment or defaults"""
        return {
            'telegram_send': int(os.getenv('CONCURRENCY_TELEGRAM_SEND', '10')),
            'telegram_fetch': int(os.getenv('CONCURRENCY_TELEGRAM_FETCH', '15')),
            'database_write': int(os.getenv('CONCURRENCY_DATABASE_WRITE', '20')),
            'database_read': int(os.getenv('CONCURRENCY_DATABASE_READ', '30')),
            'file_processing': int(os.getenv('CONCURRENCY_FILE_PROCESSING', '5')),
            'broadcast': int(os.getenv('CONCURRENCY_BROADCAST', '3')),
            'indexing': int(os.getenv('CONCURRENCY_INDEXING', '8')),
        }
    
    def validate_all(self) -> List[str]:
        """Validate all configuration sections and return errors"""
        errors = []
        
        try:
            self.telegram
        except Exception as e:
            errors.append(f"Telegram config error: {e}")
        
        try:
            self.database
        except Exception as e:
            errors.append(f"Database config error: {e}")
        
        try:
            self.redis
        except Exception as e:
            errors.append(f"Redis config error: {e}")
        
        return errors


# Global settings instance
settings = Settings()


# Backward compatibility function
def get_env(key: str, default: Any = None) -> Any:
    """
    Backward compatibility function for os.getenv calls
    Prefer using settings object directly in new code
    """
    return os.getenv(key, default)