import os
from datetime import timedelta

# OAuth 2.0 credentials
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

# Flask session configuration
SESSION_COOKIE_NAME = 'infocal_session'
PERMANENT_SESSION_LIFETIME = timedelta(days=5)
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
