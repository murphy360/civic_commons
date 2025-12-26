FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies for Playwright and PDF processing
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Copy scraper requirements first for caching
COPY workers/scraper/requirements.txt requirements-scraper.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements-scraper.txt

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p /data/pdfs /data/cache

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run the scraper
CMD ["python", "-m", "workers.scraper"]
