FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy shared directory into services so it's accessible as ../shared
RUN cp -r /app/shared /app/services/shared && \
    touch /app/services/shared/__init__.py

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose MCP port
EXPOSE 8000

# Default command runs SSE server as a module
CMD ["python", "-m", "uvicorn", "services.mcp.sse_server:app", "--host", "0.0.0.0", "--port", "8000"]
