#!/bin/sh
set -e

# Wait for database
echo "Waiting for postgres..."
while ! pg_isready -h postgres -U postgres -d qatrackplus; do
  sleep 1
done
echo "PostgreSQL started"

# Setup local_settings if not exists
if [ ! -f qatrack/local_settings.py ]; then
    echo "from .docker_settings import *" > qatrack/local_settings.py
fi

echo "Running migrations..."
python manage.py migrate --noinput

echo "Creating cache table..."
python manage.py createcachetable || true

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn..."
exec gunicorn qatrack.wsgi:application -w 2 -b 0.0.0.0:8000
