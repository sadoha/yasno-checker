# syntax=docker/dockerfile:1
# - Multi-stage build for minimal surface area
# - Runs as unprivileged non-root user (appuser)

FROM python:3.12-alpine AS builder
WORKDIR /build

# Copy only requirements to cache dependency layer
COPY requirements.txt .
# Install dependencies into a temporary prefix directory
RUN pip install --no-cache-dir --prefix=/build/install -r requirements.txt


FROM python:3.12-alpine

# Enforce secure Python execution (no bytecode writing, unbuffered stdout)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Kyiv

# Install OS timezone database (required for Python zoneinfo in Alpine)
RUN apk add --no-cache tzdata && \
    addgroup -S appgroup -g 10000 && \
    adduser -S appuser -G appgroup -u 10000

WORKDIR /app

# Copy compiled dependencies from builder
COPY --from=builder /build/install /usr/local

# Copy application script
COPY yasno_check.py .

# Restrict file ownership to non-root user
RUN chown -R appuser:appgroup /app

USER appuser

ENTRYPOINT ["python3", "yasno_check.py"]
# Provide empty CMD to allow overriding via compose/docker run args
CMD []
