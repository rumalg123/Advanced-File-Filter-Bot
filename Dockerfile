FROM python:3.13.3-slim-bookworm

# Set Railway-specific environment
ENV RAILWAY_ENVIRONMENT=true
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV USE_UVLOOP=1

# Update system and install dependencies
RUN apt update && apt upgrade -y && \
    apt install -y git build-essential locales gcc python3-dev curl && \
    sed -i 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    locale-gen && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*

# Set locale
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Copy requirements and install Python dependencies
COPY requirements.txt /requirements.txt

# Install Python packages with optimizations
RUN pip install -U pip wheel && \
    pip install -U uvloop && \
    pip install -U -r requirements.txt && \
    pip cache purge

# Set working directory
WORKDIR /app

# Copy application files
COPY . .

# Make setup script executable
RUN chmod +x railway-setup.py

# Create logs directory
RUN mkdir -p logs

# Expose port (Railway will set PORT env var)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Start with setup script that checks configuration
CMD ["python", "railway-setup.py"]