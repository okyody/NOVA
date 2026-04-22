# ── Stage 1: Build ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: Runtime ───────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install runtime system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY packages/ packages/
COPY apps/ apps/
COPY characters/ characters/
COPY knowledge/ knowledge/
COPY nova.config.example.json nova.config.example.json

# Create data directories
RUN mkdir -p data/state knowledge

# Non-root user for security
RUN useradd -m nova && chown -R nova:nova /app
USER nova

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8765/health || exit 1

EXPOSE 8765 8767 9090

CMD ["python", "-m", "uvicorn", "apps.nova_server.main:app", "--host", "0.0.0.0", "--port", "8765"]
