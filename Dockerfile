FROM python:3.13.3-slim-bookworm

# Update the package list, upgrade packages, install necessary packages including locales
RUN apt update && apt upgrade -y && \
    apt install -y git build-essential locales gcc python3-dev && \
    sed -i 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    locale-gen

# Set environment variables for the locale
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Copy requirements and install Python dependencies
COPY requirements.txt /requirements.txt

# Install with uvloop compilation
RUN pip install -U pip && \
    pip install -U wheel && \
    pip install -U uvloop && \
    pip install -U -r requirements.txt

# Set working directory and copy your application code
WORKDIR /app
COPY . .

# Expose port 8000
EXPOSE 8000

RUN chmod +x start.sh
# Set environment variable to ensure uvloop is used
ENV PYTHONUNBUFFERED=1
ENV USE_UVLOOP=1
# Start your application
CMD ["bash", "start.sh"]