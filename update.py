#!/usr/bin/env python3
"""
Secure update script for Advanced File Filter Bot.

This script safely updates the bot from a git repository with proper validation,
backup creation, and rollback capabilities.
"""

import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import argparse
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('update.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# Import centralized settings
try:
    from config import settings
    SETTINGS_AVAILABLE = True
except ImportError:
    logger.warning("Centralized settings not available, falling back to environment variables")
    SETTINGS_AVAILABLE = False

class SecureUpdater:
    """Secure bot updater with validation and rollback."""
    
    def __init__(self, 
                 repo_url: str,
                 branch: str = "main",
                 backup_dir: str = "backups"):
        self.repo_url = self._validate_repo_url(repo_url)
        self.branch = self._validate_branch(branch)
        self.backup_dir = Path(backup_dir)
        self.current_dir = Path.cwd()
        self.temp_dir: Optional[Path] = None
        
        # Docker detection
        self.in_docker = self._detect_docker_environment()
        if self.in_docker:
            logger.info("🐳 Docker environment detected")
        
    def _validate_repo_url(self, url: str) -> str:
        """Validate repository URL to prevent injection attacks."""
        if not url:
            raise ValueError("Repository URL cannot be empty")
            
        # Allow only HTTPS git URLs and GitHub URLs
        allowed_patterns = [
            "https://github.com/",
            "https://gitlab.com/",
            "https://bitbucket.org/"
        ]
        
        if not any(url.startswith(pattern) for pattern in allowed_patterns):
            raise ValueError(f"Invalid repository URL. Must start with one of: {allowed_patterns}")
            
        # Basic URL validation - no shell metacharacters
        dangerous_chars = [';', '&', '|', '`', '$', '(', ')', '{', '}', '[', ']']
        if any(char in url for char in dangerous_chars):
            raise ValueError("Repository URL contains dangerous characters")
            
        return url
        
    def _validate_branch(self, branch: str) -> str:
        """Validate git branch name."""
        if not branch:
            raise ValueError("Branch name cannot be empty")
            
        # Basic branch name validation
        if any(char in branch for char in [';', '&', '|', '`', '$', ' ']):
            raise ValueError("Branch name contains invalid characters")
            
        return branch
    
    def _detect_docker_environment(self) -> bool:
        """Detect if running inside a Docker container."""
        # Check for Docker-specific files and environment
        docker_indicators = [
            Path("/.dockerenv"),
            Path("/proc/1/cgroup")
        ]
        
        for indicator in docker_indicators:
            if indicator.exists():
                if indicator.name == "cgroup":
                    # Check if cgroup contains docker
                    try:
                        content = indicator.read_text()
                        if "docker" in content or "containerd" in content:
                            return True
                    except:
                        pass
                else:
                    return True
        
        # Check environment variables using centralized settings if available
        if SETTINGS_AVAILABLE:
            return settings.is_kubernetes or settings.is_docker
        else:
            return bool(os.getenv("KUBERNETES_SERVICE_HOST")) or bool(os.getenv("IN_DOCKER"))
        
    def _run_command(self, cmd: list, cwd: Optional[Path] = None, capture_output: bool = True) -> subprocess.CompletedProcess:
        """Safely run a command with proper error handling."""
        try:
            logger.info(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                cwd=cwd or self.current_dir,
                capture_output=capture_output,
                text=True,
                check=True,
                timeout=300  # 5 minute timeout
            )
            return result
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out: {' '.join(cmd)}")
            raise
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(cmd)}")
            logger.error(f"Exit code: {e.returncode}")
            logger.error(f"stdout: {e.stdout}")
            logger.error(f"stderr: {e.stderr}")
            raise
            
    def _create_backup(self) -> Path:
        """Create backup of current installation."""
        # Use Python for cross-platform timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        backup_path = self.backup_dir / f"backup_{timestamp}"
        backup_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Creating backup at: {backup_path}")
        
        # Files to backup (exclude temp files, logs, etc.)
        important_files = [
            "*.py", "requirements.txt", "Dockerfile", "docker-compose.yml",
            "redis.conf", "start.sh", "core/", "handlers/", "repositories/", 
            "README.md", "CLAUDE.md", ".env.example", "sample.env"
        ]
        
        for pattern in important_files:
            try:
                if "*" in pattern:
                    # Use find for glob patterns
                    files = list(self.current_dir.glob(pattern))
                else:
                    # Handle directories and specific files
                    path = self.current_dir / pattern
                    files = [path] if path.exists() else []
                    
                for file_path in files:
                    if file_path.exists():
                        relative_path = file_path.relative_to(self.current_dir)
                        dest_path = backup_path / relative_path
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        if file_path.is_file():
                            shutil.copy2(file_path, dest_path)
                        elif file_path.is_dir():
                            shutil.copytree(file_path, dest_path, dirs_exist_ok=True)
                            
            except Exception as e:
                logger.warning(f"Failed to backup {pattern}: {e}")
                
        logger.info("Backup completed successfully")
        return backup_path
        
    def _clone_repository(self) -> Path:
        """Clone repository to temporary directory."""
        self.temp_dir = Path(tempfile.mkdtemp(prefix="bot_update_"))
        logger.info(f"Cloning repository to: {self.temp_dir}")
        
        # Clone with specific branch
        self._run_command([
            "git", "clone",
            "--branch", self.branch,
            "--single-branch",
            "--depth", "1",  # Shallow clone for security and speed
            self.repo_url,
            str(self.temp_dir / "source")
        ])
        
        return self.temp_dir / "source"
        
    def _validate_update(self, source_dir: Path) -> bool:
        """Validate the cloned repository before applying update."""
        logger.info("Validating update...")
        
        # Check for required files
        required_files = ["bot.py", "requirements.txt"]
        for file_name in required_files:
            if not (source_dir / file_name).exists():
                logger.error(f"Required file missing: {file_name}")
                return False
                
        # Validate Python syntax of main files
        python_files = ["bot.py"]
        for file_name in python_files:
            try:
                with open(source_dir / file_name, 'r', encoding='utf-8') as f:
                    compile(f.read(), file_name, 'exec')
            except SyntaxError as e:
                logger.error(f"Syntax error in {file_name}: {e}")
                return False
            except Exception as e:
                logger.error(f"Error validating {file_name}: {e}")
                return False
                
        # Check requirements.txt format
        try:
            with open(source_dir / "requirements.txt", 'r') as f:
                lines = f.readlines()
                for line_num, line in enumerate(lines, 1):
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Basic package name validation - allow semicolons for conditional dependencies
                        dangerous_chars = ['&', '|', '`', '$(']
                        if any(char in line for char in dangerous_chars):
                            logger.error(f"Suspicious content in requirements.txt line {line_num}: {line}")
                            return False
        except Exception as e:
            logger.error(f"Error validating requirements.txt: {e}")
            return False
            
        logger.info("Update validation passed")
        return True
        
    def _apply_update(self, source_dir: Path) -> None:
        """Apply the update by copying files."""
        logger.info("Applying update...")
        
        # Files and directories to update
        update_items = [
            "bot.py", "requirements.txt", "Dockerfile", "docker-compose.yml",
            "redis.conf", "start.sh", "update.py",
            "core/", "handlers/", "repositories/"
        ]
        
        # Add Docker-specific handling
        if self.in_docker:
            logger.info("📦 Applying Docker-aware update...")
            # In Docker, we might have permission issues with some files
            # Skip certain files that are handled by the container build process
            update_items = [item for item in update_items if item not in ["Dockerfile"]]
        
        for item_name in update_items:
            source_path = source_dir / item_name
            dest_path = self.current_dir / item_name
            
            if not source_path.exists():
                logger.warning(f"Source item not found, skipping: {item_name}")
                continue
                
            try:
                if source_path.is_file():
                    shutil.copy2(source_path, dest_path)
                    logger.info(f"Updated file: {item_name}")
                elif source_path.is_dir():
                    if dest_path.exists():
                        shutil.rmtree(dest_path)
                    shutil.copytree(source_path, dest_path)
                    logger.info(f"Updated directory: {item_name}")
            except Exception as e:
                logger.error(f"Failed to update {item_name}: {e}")
                raise
                
        logger.info("Update applied successfully")
        
    def _cleanup(self) -> None:
        """Clean up temporary directory."""
        if self.temp_dir and self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
                logger.info("Temporary directory cleaned up")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp directory: {e}")
                
    def update(self, skip_backup: bool = False) -> bool:
        """Perform secure update with backup and validation."""
        backup_path: Optional[Path] = None
        
        try:
            logger.info("Starting secure update process...")
            
            # Create backup unless skipped
            if not skip_backup:
                backup_path = self._create_backup()
                
            # Clone repository
            source_dir = self._clone_repository()
            
            # Validate update
            if not self._validate_update(source_dir):
                logger.error("Update validation failed. Aborting.")
                return False
                
            # Apply update
            self._apply_update(source_dir)
            
            logger.info("Update completed successfully!")
            if backup_path:
                logger.info(f"💾 Backup available at: {backup_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Update failed: {e}")
            if backup_path:
                logger.info(f"💾 Backup available for manual rollback at: {backup_path}")
            return False
            
        finally:
            self._cleanup()
            
    def rollback(self, backup_path: str) -> bool:
        """Rollback to a previous backup."""
        backup_dir = Path(backup_path)
        
        if not backup_dir.exists():
            logger.error(f"Backup directory not found: {backup_path}")
            return False
            
        try:
            logger.info(f"Rolling back to: {backup_path}")
            
            # Copy backup files back
            for item in backup_dir.iterdir():
                dest_path = self.current_dir / item.name
                
                if item.is_file():
                    shutil.copy2(item, dest_path)
                elif item.is_dir():
                    if dest_path.exists():
                        shutil.rmtree(dest_path)
                    shutil.copytree(item, dest_path)
                    
            logger.info("Rollback completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Secure updater for Advanced File Filter Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python update.py --repo https://github.com/rumalg123/Advanced-File-Filter-Bot.git
  python update.py --repo https://github.com/rumalg123/Advanced-File-Filter-Bot.git --branch main
  python update.py --rollback backups/backup_20231201_120000
        """
    )
    
    # Get default values from centralized settings if available
    if SETTINGS_AVAILABLE:
        default_repo = settings.updates.repo
        default_branch = settings.updates.branch
    else:
        default_repo = os.getenv("UPDATE_REPO", "https://github.com/rumalg123/Advanced-File-Filter-Bot.git")
        default_branch = os.getenv("UPDATE_BRANCH", "main")
    
    parser.add_argument(
        "--repo", "--repository",
        help="Repository URL (HTTPS only)",
        default=default_repo
    )
    
    parser.add_argument(
        "--branch",
        help="Git branch to update from",
        default=default_branch
    )
    
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Skip backup creation (not recommended)"
    )
    
    parser.add_argument(
        "--rollback",
        help="Rollback to specified backup directory"
    )
    
    args = parser.parse_args()
    
    try:
        updater = SecureUpdater(args.repo, args.branch)
        
        if args.rollback:
            success = updater.rollback(args.rollback)
        else:
            if not args.repo:
                logger.error("Repository URL is required. Use --repo or set UPDATE_REPO environment variable.")
                sys.exit(1)
                
            success = updater.update(skip_backup=args.skip_backup)
            
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"Update script failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()