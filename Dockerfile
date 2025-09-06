# Use a lightweight Python base image with proper package management
FROM python:3.13.7-slim

# Set the working directory
WORKDIR /usr/src/app

# Install system dependencies including git for auto-updates
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    ca-certificates \
    locales \
    gcc \
    python3-dev \
    && sed -i 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables for the locale
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Create directories for persistent data
RUN mkdir -p /usr/src/app/backups \
             /usr/src/app/logs \
             /usr/src/app/.git

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with uvloop optimization
RUN pip install --no-cache-dir --upgrade pip wheel && \
    pip install --no-cache-dir uvloop && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Make scripts executable
RUN chmod +x start.sh && \
    chmod +x update.py

# Create non-root user for security
RUN groupadd -r botuser && useradd -r -g botuser -d /usr/src/app -s /sbin/nologin botuser && \
    chown -R botuser:botuser /usr/src/app

# Switch to non-root user
USER botuser

# Configure git for container environment as botuser
RUN git config --global --add safe.directory /usr/src/app && \
    git config --global user.email "bot@filefilterbot.com" && \
    git config --global user.name "Advanced File Filter Bot" && \
    git config --global init.defaultBranch main

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python3 -c "import requests; requests.get('http://localhost:8000/health', timeout=5)" || exit 1

# Default environment variables for auto-update
ENV AUTO_UPDATE=${AUTO_UPDATE:-false}
ENV UPDATE_ON_START=${UPDATE_ON_START:-false}
ENV BACKUP_ON_UPDATE=${BACKUP_ON_UPDATE:-true}

# Set Python optimizations
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV USE_UVLOOP=1

# Expose port 8000
EXPOSE 8000

# Run the application with auto-update support
CMD ["bash", "start.sh"]