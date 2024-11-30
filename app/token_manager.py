from cryptography.fernet import Fernet
import base64
import os
from datetime import datetime, timedelta
import requests
import threading
import time
from logging import Logger

class TokenManager:
    def __init__(self, logger: Logger, secret_key=None):
        if secret_key is None:
            secret_key = os.environ.get('ENCRYPTION_KEY')
            if not secret_key:
                # Generate a new key if none exists
                key = Fernet.generate_key()
                self.fernet = Fernet(key)
            else:
                # Use the key from environment
                self.fernet = Fernet(secret_key.encode())
        else:
            self.fernet = Fernet(secret_key)
        
        self.logger = logger
        self.refresh_thread = None
        self.stop_refresh = False

    def encrypt_token(self, token: str) -> str:
        """Encrypt a token string."""
        return self.fernet.encrypt(token.encode()).decode()

    def decrypt_token(self, encrypted_token: str) -> str:
        """Decrypt an encrypted token string."""
        try:
            return self.fernet.decrypt(encrypted_token.encode()).decode()
        except Exception as e:
            self.logger.error(f"Error decrypting token: {e}")
            return None

    def start_token_refresh_thread(self, db, google_config):
        """Start a background thread to refresh tokens"""
        if self.refresh_thread is None:
            self.stop_refresh = False
            self.refresh_thread = threading.Thread(
                target=self._token_refresh_loop,
                args=(db, google_config),
                daemon=True
            )
            self.refresh_thread.start()
            self.logger.info("Token refresh thread started")

    def stop_token_refresh_thread(self):
        """Stop the token refresh thread"""
        self.stop_refresh = True
        if self.refresh_thread:
            self.refresh_thread = None
            self.logger.info("Token refresh thread stopped")

    def _token_refresh_loop(self, db, google_config):
        """Background loop to refresh tokens"""
        while not self.stop_refresh:
            try:
                # Find users with refresh tokens that need to be refreshed
                users = db.users.find({'refresh_token': {'$exists': True}})
                
                for user in users:
                    try:
                        # Decrypt refresh token
                        refresh_token = self.decrypt_token(user['refresh_token'])
                        if not refresh_token:
                            continue

                        # Request new access token
                        new_tokens = self._refresh_google_token(
                            refresh_token,
                            google_config['client_id'],
                            google_config['client_secret']
                        )

                        if new_tokens and 'refresh_token' in new_tokens:
                            # Encrypt and store new refresh token
                            encrypted_token = self.encrypt_token(new_tokens['refresh_token'])
                            db.users.update_one(
                                {'_id': user['_id']},
                                {'$set': {
                                    'refresh_token': encrypted_token,
                                    'token_updated_at': datetime.utcnow()
                                }}
                            )
                            self.logger.info(f"Refreshed token for user: {user['email']}")

                    except Exception as e:
                        self.logger.error(f"Error refreshing token for user {user.get('email')}: {e}")

            except Exception as e:
                self.logger.error(f"Error in token refresh loop: {e}")

            # Sleep for 1 hour before next refresh check
            time.sleep(3600)

    def _refresh_google_token(self, refresh_token: str, client_id: str, client_secret: str) -> dict:
        """Refresh Google OAuth token"""
        try:
            response = requests.post(
                'https://oauth2.googleapis.com/token',
                data={
                    'client_id': client_id,
                    'client_secret': client_secret,
                    'refresh_token': refresh_token,
                    'grant_type': 'refresh_token'
                }
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                self.logger.error(f"Token refresh failed: {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error refreshing Google token: {e}")
            return None
