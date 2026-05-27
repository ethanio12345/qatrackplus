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
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /usr/src/qatrackplus
# Cache bust 2
COPY . .

# Ensure necessary directories exist
RUN mkdir -p logs qatrack/media qatrack/static


# Make entrypoint executable
RUN sed -i 's/\r$//' deploy/docker/django/entrypoint.sh && chmod +x deploy/docker/django/entrypoint.sh

EXPOSE 8000
CMD ["/usr/src/qatrackplus/deploy/docker/django/entrypoint.sh"]
# Cache bust 1
