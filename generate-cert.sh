#!/bin/bash

# Create SSL directory if it doesn't exist
mkdir -p nginx/ssl

# Generate self-signed certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout nginx/ssl/nginx.key \
    -out nginx/ssl/nginx.crt \
    -subj "/C=AT/ST=Vienna/L=Vienna/O=Development/CN=localhost"

# Set correct permissions
chmod 644 nginx/ssl/nginx.crt
chmod 644 nginx/ssl/nginx.key

echo "SSL certificate generated successfully!"
