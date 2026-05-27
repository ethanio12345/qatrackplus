# Builder stage
FROM python:3.12-bookworm AS builder

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    python3-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/qatrackplus
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY qatrack ./qatrack
# Install dependencies
RUN pip install ".[docker,postgres]" django-extensions

# Runtime stage
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y \
    postgresql-client \
    cifs-utils \
    chromium \
    libpq5 \
    curl \
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /usr/src/qatrackplus
# Cache bust 2
COPY . .

# Ensure necessary directories exist
RUN mkdir -p logs qatrack/media qatrack/static

# Make entrypoint executable
RUN ls -la deploy/docker/django/
RUN cat -v deploy/docker/django/entrypoint.sh || true
RUN dos2unix deploy/docker/django/entrypoint.sh && chmod +x deploy/docker/django/entrypoint.sh
RUN ls -la deploy/docker/django/
RUN cat -v deploy/docker/django/entrypoint.sh || true

# Add non-root user and change ownership
RUN groupadd -r -g 1000 qatrack && useradd -r -g qatrack -u 1000 qatrack && \
    chown -R qatrack:qatrack logs qatrack/media qatrack/static deploy/docker/django/entrypoint.sh


USER qatrack

EXPOSE 8000
CMD ["/usr/src/qatrackplus/deploy/docker/django/entrypoint.sh"]
# Cache bust 1
