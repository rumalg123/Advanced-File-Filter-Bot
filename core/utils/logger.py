import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional


class CentralizedLogger:
    """Centralized logging system with file rotation and console output"""

    _instance: Optional['CentralizedLogger'] = None
    _initialized = False

    def __new__(cls) -> 'CentralizedLogger':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._initialized = True
            self.log_dir = Path("logs")
            self.log_file = self.log_dir / "bot.txt"
            self.max_bytes = 5 * 1024 * 1024  # 5MB
            self.backup_count = 5  # Keep 5 backup files
            self.setup_logging()

    def setup_logging(self):
        """Setup logging configuration"""
        # Create logs directory if it doesn't exist
        self.log_dir.mkdir(exist_ok=True)

        # Create root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # Clear existing handlers
        root_logger.handlers.clear()

        # Create formatter
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # File handler with rotation
        file_handler = logging.handlers.RotatingFileHandler(
            filename=self.log_file,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        # Add handlers to root logger
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

        # Set specific logger levels
        self._configure_logger_levels()

        # Log startup message
        logging.info("Centralized logging system initialized")
        logging.info(f"Log file: {self.log_file}")
        logging.info(f"Max file size: {self.max_bytes / 1024 / 1024:.1f}MB")
        logging.info(f"Backup count: {self.backup_count}")

    def _configure_logger_levels(self):
        """Configure specific logger levels"""
        # Reduce noise from external libraries
        logging.getLogger("pyrogram").setLevel(logging.WARNING)
        logging.getLogger("pymongo").setLevel(logging.WARNING)
        logging.getLogger("motor").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

        # Bot specific loggers
        logging.getLogger("bot").setLevel(logging.INFO)
        logging.getLogger("handlers").setLevel(logging.INFO)
        logging.getLogger("services").setLevel(logging.INFO)
        logging.getLogger("repositories").setLevel(logging.INFO)
        logging.getLogger("core").setLevel(logging.INFO)

    def get_logger(self, name: str) -> logging.Logger:
        """Get a logger instance for a specific module"""
        return logging.getLogger(name)

    def set_level(self, level: str):
        """Set global logging level"""
        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }

        if level.upper() in level_map:
            logging.getLogger().setLevel(level_map[level.upper()])
            logging.info(f"Logging level set to: {level.upper()}")
        else:
            logging.warning(f"Invalid logging level: {level}")

    def log_system_info(self):
        """Log system information"""
        import platform
        import psutil

        logging.info("=" * 50)
        logging.info("SYSTEM INFORMATION")
        logging.info("=" * 50)
        logging.info(f"Platform: {platform.platform()}")
        logging.info(f"Python Version: {platform.python_version()}")
        logging.info(f"CPU Count: {psutil.cpu_count()}")
        logging.info(f"Memory: {psutil.virtual_memory().total / 1024 ** 3:.1f}GB")
        logging.info(f"Working Directory: {os.getcwd()}")
        logging.info("=" * 50)

    def log_config_info(self, config):
        """Log configuration information (without sensitive data)"""
        logging.info("=" * 50)
        logging.info("BOT CONFIGURATION")
        logging.info("=" * 50)
        logging.info(f"Bot Session: {config.SESSION}")
        logging.info(f"Database Name: {config.DATABASE_NAME}")
        logging.info(f"Collection Name: {config.COLLECTION_NAME}")
        logging.info(f"Workers: {config.WORKERS}")
        logging.info(f"Port: {config.PORT}")
        logging.info(f"Premium Disabled: {config.DISABLE_PREMIUM}")
        logging.info(f"Daily Limit: {config.NON_PREMIUM_DAILY_LIMIT}")
        logging.info(f"Premium Duration: {config.PREMIUM_DURATION_DAYS} days")
        logging.info(f"Message Delete Time: {config.MESSAGE_DELETE_SECONDS}s")
        logging.info(f"Max Button Size: {config.MAX_BTN_SIZE}")
        logging.info(f"Admin Count: {len(config.ADMINS)}")
        logging.info(f"Channel Count: {len(config.CHANNELS)}")
        logging.info(f"Auth Channel: {'Set' if config.AUTH_CHANNEL else 'Not set'}")
        logging.info(f"Auth Groups: {len(config.AUTH_GROUPS)}")
        logging.info(f"Log Channel: {'Set' if config.LOG_CHANNEL else 'Not set'}")
        logging.info(f"Delete Channel: {'Set' if config.DELETE_CHANNEL else 'Not set'}")
        logging.info("=" * 50)


# Global instance
_logger_instance = CentralizedLogger()


# Convenience functions for easy usage
def get_logger(name: str = None) -> logging.Logger:
    """Get a logger instance"""
    if name is None:
        # Get the calling module name
        import inspect
        frame = inspect.currentframe().f_back
        module = inspect.getmodule(frame)
        name = module.__name__ if module else __name__

    return _logger_instance.get_logger(name)


def setup_logging():
    """Setup centralized logging - called once at startup"""
    return _logger_instance


def set_log_level(level: str):
    """Set global logging level"""
    _logger_instance.set_level(level)


def log_system_info():
    """Log system information"""
    _logger_instance.log_system_info()


def log_config_info(config):
    """Log configuration information"""
    _logger_instance.log_config_info(config)


# Module-level logger for this file
logger = get_logger(__name__)