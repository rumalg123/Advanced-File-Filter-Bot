# start.sh - Optimized startup script for Linux with uvloop
#!/bin/bash

# Set ulimit for better performance
ulimit -n 100000  # Increase file descriptor limit
ulimit -u 32768   # Increase process limit

# Enable core dumps for debugging (optional)
ulimit -c unlimited

# Set Python optimizations
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# Use uvloop if available
export USE_UVLOOP=1

# TCP optimizations for Linux
if [ -f /proc/sys/net/core/somaxconn ]; then
    echo 1024 > /proc/sys/net/core/somaxconn 2>/dev/null || true
fi

# Check if uvloop is installed
python3 -c "import uvloop" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ uvloop detected - running in high performance mode"
else
    echo "⚠️ uvloop not found - installing..."
    pip install uvloop
fi
if python3 -O update.py; then
  echo "Update step completed."
else
  echo "Update step failed (continuing anyway)..." >&2
fi
# Run the bot
exec python3 -O bot.py # -O flag for optimizations