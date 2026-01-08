
# Python 3.11 slim image for smaller footprint
FROM python:3.11-slim

# Set timezone
ENV TZ=Asia/Ulaanbaatar

# Standard Python buffers setup
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (if any needed for numpy/pandas extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Expose port (internal)
EXPOSE 8000

# Run uvicorn with 0.0.0.0 to accessible externally in container
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
