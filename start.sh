#!/bin/bash
set -euo pipefail

# Advanced File Filter Bot Startup Script with Auto-Update Support
# This script handles bot startup, updates, and basic maintenance tasks
# Supports both local and Docker container environments

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_NAME="Advanced File Filter Bot"
LOG_DIR="$SCRIPT_DIR/logs"
VENV_DIR="$SCRIPT_DIR/.venv"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"

# Auto-update configuration from environment
UPDATE_REPO="${UPDATE_REPO:-https://github.com/rumalg123/Advanced-File-Filter-Bot}"
UPDATE_BRANCH="${UPDATE_BRANCH:-main}"
AUTO_UPDATE="${AUTO_UPDATE:-false}"
UPDATE_ON_START="${UPDATE_ON_START:-false}"
BACKUP_ON_UPDATE="${BACKUP_ON_UPDATE:-true}"

# Docker detection
IN_DOCKER="${IN_DOCKER:-false}"
if [ -f /.dockerenv ] || [ -n "${KUBERNETES_SERVICE_HOST:-}" ]; then
    IN_DOCKER="true"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Helper functions
check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "$1 is not installed or not in PATH"
        return 1
    fi
    return 0
}

wait_for_input() {
    echo -n "Press Enter to continue or Ctrl+C to cancel..."
    read -r
}

# Setup functions
setup_directories() {
    log_step "Setting up directories"
    mkdir -p "$LOG_DIR"
    mkdir -p "backups"
    log_info "Directories created successfully"
}

setup_python_env() {
    log_step "Setting up Python environment"
    
    # Skip virtual environment setup in Docker
    if [ "$IN_DOCKER" = "true" ]; then
        log_info "Running in Docker container, skipping virtual environment setup"
        
        # Check Python version
        local python_version
        python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        log_info "Found Python $python_version"
        
        # Install/upgrade requirements if file exists and has been updated
        if [ -f "$REQUIREMENTS_FILE" ]; then
            log_info "Checking Python dependencies"
            pip install --user --no-deps --upgrade -r "$REQUIREMENTS_FILE" >/dev/null 2>&1
        fi
        
        log_info "Python environment ready (Docker mode)"
        return 0
    fi
    
    # Local environment setup
    # Check Python version
    if ! check_command python3; then
        log_error "Python 3 is required but not found"
        exit 1
    fi
    
    local python_version
    python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log_info "Found Python $python_version"
    
    # Create virtual environment if it doesn't exist
    if [ ! -d "$VENV_DIR" ]; then
        log_info "Creating Python virtual environment"
        python3 -m venv "$VENV_DIR"
    fi
    
    # Activate virtual environment
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"
    
    # Upgrade pip
    log_info "Upgrading pip"
    pip install --upgrade pip
    
    # Install requirements
    if [ -f "$REQUIREMENTS_FILE" ]; then
        log_info "Installing Python dependencies"
        pip install -r "$REQUIREMENTS_FILE"
    else
        log_warn "requirements.txt not found, skipping dependency installation"
    fi
    
    log_info "Python environment setup complete"
}

check_config() {
    log_step "Checking configuration"
    
    # Check for required files
    local required_files=("bot.py" "requirements.txt")
    for file in "${required_files[@]}"; do
        if [ ! -f "$SCRIPT_DIR/$file" ]; then
            log_error "Required file missing: $file"
            exit 1
        fi
    done
    
    # Check for env files and/or platform environment variables
    local env_file_found=false
    if [ -f "$SCRIPT_DIR/config.env" ] || [ -f "$SCRIPT_DIR/.env" ]; then
        env_file_found=true
    fi

    # Validate presence of required environment variables when no .env is present
    local required_vars=("BOT_TOKEN" "API_ID" "API_HASH" "ADMINS" "DATABASE_URI" "REDIS_URI")
    local missing_vars=()
    for var in "${required_vars[@]}"; do
        if [ -z "${!var:-}" ]; then
            missing_vars+=("$var")
        fi
    done

    if [ "$env_file_found" = false ]; then
        if [ ${#missing_vars[@]} -eq 0 ]; then
            # Running without .env, but all required vars are present (e.g., Railway/Heroku)
            log_warn "No config.env or .env file found"
            log_info "Environment variables detected via platform — continuing without .env"
        else
            log_warn "No config.env or .env file found"
            log_warn "Missing required environment variables: ${missing_vars[*]}"
            echo
            echo "Required environment variables:"
            echo "  - BOT_TOKEN: Your Telegram bot token"
            echo "  - API_ID: Your Telegram API ID"
            echo "  - API_HASH: Your Telegram API hash"
            echo "  - ADMINS: Admin user IDs (comma separated)"
            echo "  - DATABASE_URI: MongoDB connection string"
            echo "  - REDIS_URI: Redis connection URL (required)"
            echo
            echo "Optional variables:"
            echo "  - LOG_CHANNEL: Channel ID for bot logs"
            echo "  - AUTH_CHANNEL: Force subscription channel"
            echo "  - SUPPORT_GROUP_ID: Support group for #request feature"
            echo
            # If interactive TTY, allow continuing; otherwise fail fast
            if [ -t 0 ]; then
                wait_for_input
            else
                log_error "Non-interactive environment and missing variables — exiting"
                exit 1
            fi
        fi
    fi

    log_info "Configuration check complete"
}

# Auto-update functions
auto_update_check() {
    log_step "Checking auto-update configuration"
    
    if [ "$AUTO_UPDATE" = "true" ] || [ "$UPDATE_ON_START" = "true" ]; then
        log_info "Auto-update enabled"
        return 0
    else
        log_info "Auto-update disabled"
        return 1
    fi
}

run_secure_update() {
    log_step "Running secure update"
    
    if [ -z "$UPDATE_REPO" ]; then
        log_warn "UPDATE_REPO not set, skipping update"
        return 0
    fi
    
    if [ ! -f "$SCRIPT_DIR/update.py" ]; then
        log_error "update.py not found, cannot perform update"
        return 1
    fi
    
    log_info "Updating from repository: $UPDATE_REPO"
    log_info "Branch: $UPDATE_BRANCH"
    log_info "Backup on update: $BACKUP_ON_UPDATE"
    
    # Prepare update command
    local update_cmd="python3 \"$SCRIPT_DIR/update.py\" --repo \"$UPDATE_REPO\" --branch \"$UPDATE_BRANCH\""
    
    # Skip backup if disabled
    if [ "$BACKUP_ON_UPDATE" = "false" ]; then
        update_cmd="$update_cmd --skip-backup"
        log_warn "Backup creation disabled - no rollback will be possible"
    fi
    
    # Run the secure update script
    log_info "Executing update command..."
    if eval "$update_cmd"; then
        log_info "✅ Update completed successfully"
        
        # Reinstall dependencies if requirements changed
        if [ -f "$REQUIREMENTS_FILE" ]; then
            log_info "Checking dependencies after update"
            
            if [ "$IN_DOCKER" = "true" ]; then
                # In Docker, install user packages quietly
                pip install --user --no-deps -r "$REQUIREMENTS_FILE" >/dev/null 2>&1
            else
                # Local environment with virtual environment
                # shellcheck source=/dev/null
                source "$VENV_DIR/bin/activate"
                pip install --no-deps -r "$REQUIREMENTS_FILE" >/dev/null 2>&1
            fi
        fi
        
        # Show update summary
        log_info "📄 Update summary:"
        log_info "  - Repository: $UPDATE_REPO"
        log_info "  - Branch: $UPDATE_BRANCH"
        log_info "  - Backup created: $BACKUP_ON_UPDATE"
        log_info "  - Environment: $([ "$IN_DOCKER" = "true" ] && echo "Docker" || echo "Local")"
        
        return 0
    else
        log_error "❌ Update failed"
        
        if [ "$BACKUP_ON_UPDATE" = "true" ]; then
            log_info "💾 Backup should be available in backups/ directory for manual rollback"
            log_info "    Use: python3 update.py --rollback backups/backup_YYYYMMDD_HHMMSS"
        fi
        
        return 1
    fi
}

# Container restart function for post-update
request_container_restart() {
    if [ "$IN_DOCKER" = "true" ]; then
        log_info "🔄 Container restart may be needed for complete update"
        log_info "   Run: docker-compose restart file-filter-bot"
        
        # Create restart indicator file
        touch "$SCRIPT_DIR/.restart_needed"
    fi
}

# Health check functions
check_services() {
    log_step "Checking service dependencies"
    
    # Check Redis (if configured to use external Redis)
    if [ "${REDIS_URI:-}" != "" ] && [[ "$REDIS_URI" != "redis://redis:6379"* ]]; then
        if command -v redis-cli &> /dev/null; then
            local redis_host redis_port
            redis_host=$(echo "$REDIS_URI" | sed -E 's|redis://([^:]+):.*|\1|')
            redis_port=$(echo "$REDIS_URI" | sed -E 's|redis://[^:]+:([0-9]+).*|\1|')
            
            if redis-cli -h "$redis_host" -p "$redis_port" ping >/dev/null 2>&1; then
                log_info "Redis connection: OK"
            else
                log_warn "Redis connection: FAILED"
            fi
        else
            log_warn "redis-cli not available, skipping Redis check"
        fi
    fi
    
    # Check MongoDB connectivity (basic check)
    if [ "${DATABASE_URI:-}" != "" ]; then
        if command -v mongosh &> /dev/null || command -v mongo &> /dev/null; then
            log_info "MongoDB client available"
        else
            log_warn "No MongoDB client found, skipping connection test"
        fi
    fi
    
    log_info "Service dependency check complete"
}

check_performance_features() {
    log_step "Checking performance features"
    
    # Check if uvloop is available
    if python3 -c "import uvloop" 2>/dev/null; then
        log_info "✅ uvloop detected - high performance mode available"
    else
        log_warn "⚠️ uvloop not available (continuing without it)"
        
        # Try to install uvloop if we're not in Docker and have pip
        if [ "$IN_DOCKER" != "true" ] && command -v pip &> /dev/null; then
            log_info "Attempting to install uvloop for better performance..."
            pip install uvloop || log_warn "Failed to install uvloop"
        fi
    fi
    
    # Try to optimize kernel network settings (ignore failures in containers)
    if echo 65536 > /proc/sys/net/core/somaxconn 2>/dev/null; then
        log_info "Kernel network settings optimized"
    else
        log_warn "Cannot modify kernel settings (expected in containers)"
    fi
    
    # Set ulimit for better performance
    ulimit -n 100000 2>/dev/null && log_info "File descriptor limit increased" || log_warn "Cannot increase file descriptor limit"
    ulimit -u 32768 2>/dev/null && log_info "Process limit increased" || log_warn "Cannot increase process limit"
}

# Main functions
start_bot() {
    log_step "Starting $BOT_NAME"
    
    # Activate virtual environment (skip in Docker)
    if [ "$IN_DOCKER" != "true" ]; then
        # shellcheck source=/dev/null
        source "$VENV_DIR/bin/activate"
    fi
    
    # Change to script directory
    cd "$SCRIPT_DIR"
    
    # Create log file with timestamp
    local log_file="$LOG_DIR/bot_$(date +%Y%m%d_%H%M%S).log"
    
    # Create a symlink for easy access (current.log)
    local current_log="$LOG_DIR/current.log"
    if [ -L "$current_log" ]; then
        rm "$current_log"
    fi
    ln -sf "$(basename "$log_file")" "$current_log" 2>/dev/null || true
    
    # Set Python optimizations
    export PYTHONUNBUFFERED=1
    export PYTHONDONTWRITEBYTECODE=1
    export USE_UVLOOP=1
    
    # Start the bot
    log_info "Bot starting... Logs: $log_file"
    echo
    echo -e "${BOLD}=== $BOT_NAME Starting ===${NC}"
    echo
    
    # Run with proper error handling and Python optimizations
    if python3 -O bot.py 2>&1 | tee "$log_file"; then
        log_info "Bot exited normally"
    else
        log_error "Bot exited with error code $?"
        exit 1
    fi
}

show_usage() {
    echo -e "${BOLD}Advanced File Filter Bot Startup Script${NC}"
    echo
    echo "Usage: $0 [OPTIONS]"
    echo
    echo "Options:"
    echo "  --update          Run update before starting (if UPDATE_REPO is set)"
    echo "  --setup           Run initial setup only (create venv, install deps)"
    echo "  --check           Run health checks only"  
    echo "  --start           Start the bot (default)"
    echo "  --help            Show this help message"
    echo
    echo "Environment Variables:"
    echo "  UPDATE_REPO       Repository URL for updates (default: https://github.com/rumalg123/Advanced-File-Filter-Bot)"
    echo "  UPDATE_BRANCH     Git branch for updates (default: main)"
    echo "  AUTO_UPDATE       Auto-update on every start (default: false)"
    echo "  UPDATE_ON_START   Update once on start (default: false)"
    echo "  BACKUP_ON_UPDATE  Create backup during updates (default: true)"
    echo
    echo "Examples:"
    echo "  $0                                    # Start bot normally"
    echo "  $0 --setup                           # Setup environment only"
    echo "  $0 --update                          # Update then start"
    echo "  UPDATE_REPO=https://github.com/user/repo.git $0 --update"
    echo
}

# Main script logic
main() {
    local run_update=false
    local setup_only=false
    local check_only=false
    local show_help=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --update)
                run_update=true
                shift
                ;;
            --setup)
                setup_only=true
                shift
                ;;
            --check)
                check_only=true
                shift
                ;;
            --help)
                show_help=true
                shift
                ;;
            --start)
                # Default behavior, just consume the argument
                shift
                ;;
            *)
                log_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done
    
    if [ "$show_help" = true ]; then
        show_usage
        exit 0
    fi
    
    # Show banner
    echo -e "${BOLD}=== $BOT_NAME Startup Script ===${NC}"
    echo "Directory: $SCRIPT_DIR"
    echo "Timestamp: $(date)"
    echo
    
    # Always setup directories
    setup_directories
    
    # Run setup
    setup_python_env
    
    if [ "$setup_only" = true ]; then
        log_info "Setup completed successfully"
        exit 0
    fi
    
    # Check configuration
    check_config
    
    # Run health checks
    if [ "$check_only" = true ]; then
        check_services
        check_performance_features
        log_info "Health checks completed"
        exit 0
    fi
    
    # Auto-update logic
    if [ "$run_update" = true ] || auto_update_check; then
        log_info "🔄 Starting update process..."
        
        if ! run_secure_update; then
            log_error "Update failed, aborting startup"
            
            # In Docker, we might want to continue with old version
            if [ "$IN_DOCKER" = "true" ] && [ "${CONTINUE_ON_UPDATE_FAIL:-false}" = "true" ]; then
                log_warn "Continuing with current version due to CONTINUE_ON_UPDATE_FAIL=true"
            else
                exit 1
            fi
        else
            # Mark successful update
            echo "$(date '+%Y-%m-%d %H:%M:%S')" > "$SCRIPT_DIR/.last_update"
            request_container_restart
        fi
    fi
    
    # Final health check and performance setup
    check_services
    check_performance_features
    
    # Start the bot
    start_bot
}

# Handle signals gracefully
trap 'log_info "Script interrupted by user"; exit 130' INT TERM

# Run main function with all arguments
main "$@"
