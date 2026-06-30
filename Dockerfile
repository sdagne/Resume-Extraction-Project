# Dockerfile

# ─── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.11 AS builder

WORKDIR /app

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential       \
    gcc                   \
    g++                   \
    libglib2.0-0          \
    libsm6                \
    libxext6              \
    libxrender-dev        \
    libgomp1              \
    libgl1                \
    libglib2.0-dev        \
    wget                  \
    curl                  \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --user -r requirements.txt

# Download spaCy model
RUN python -m spacy download en_core_web_md

# ─── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Set environment variables for the runtime user
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0          \
    libsm6                \
    libxext6              \
    libxrender-dev        \
    libgomp1              \
    libgl1                \
    curl                  \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and directories, and set permissions explicitly
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/uploads /app/exports /app/temp /app/logs && \
    chown -R appuser:appuser /app && \
    chmod -R 775 /app/logs /app/uploads /app/exports /app/temp

# Copy installed packages from builder to the appuser's local path
COPY --from=builder /root/.local /home/appuser/.local
RUN chown -R appuser:appuser /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser . .

# Ensure correct ownership for writable directories
RUN chown -R appuser:appuser /app/logs /app/uploads /app/exports /app/temp

# Switch to non-root user
USER appuser

# Environment defaults
ENV PYTHONUNBUFFERED=1      \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production      \
    HOST=0.0.0.0            \
    PORT=8000               \
    LOG_LEVEL=INFO

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start command
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0",                        \
     "--port", "8000",                            \
     "--workers", "4",                            \
     "--log-level", "info",                       \
     "--proxy-headers",                           \
     "--forwarded-allow-ips", "*"]
