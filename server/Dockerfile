FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose MCP port
EXPOSE 8000

# Default command runs SSE server
CMD ["uvicorn", "sse_server:app", "--host", "0.0.0.0", "--port", "8000"]
