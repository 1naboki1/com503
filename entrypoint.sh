#!/bin/bash

# Create logs directory if it doesn't exist
mkdir -p /app/logs

# Ensure proper permissions
chown -R appuser:appuser /app/logs
chmod -R 755 /app/logs

# Start gunicorn
exec gunicorn --bind 0.0.0.0:5000 --worker-class gevent --workers 1 "app:create_app()"
