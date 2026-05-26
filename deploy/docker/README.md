# QATrack+ Docker Deployment

This folder contains the Docker configuration for running QATrack+ in a modern, production-ready environment using Docker Compose V2.

## Directory Layout
- `compose.yaml`: The production-ready defaults.
- `compose.override.yaml`: Development overrides (e.g., binding local source code).
- `django/`: Multi-stage Dockerfile and entrypoint script for the Django app.
- `nginx/`: NGINX configuration and server blocks.
- `backup/`: A lightweight Alpine container that automatically runs database and media backups via cron.

## How to Run

### Development
1. Copy `.env.example` to `.env` and set your credentials.
2. Run `docker-compose up` (or `docker compose up`).
By default, Docker Compose will read both `compose.yaml` and `compose.override.yaml`, mapping your local source code into the container for live reloading.

### Production
1. Copy `.env.example` to `.env` and configure strong passwords.
2. Review the NGINX TLS config in `nginx/conf.d/tls.conf.example`.
3. Run using only the production file:
   ```bash
   docker compose -f compose.yaml up -d
   ```
