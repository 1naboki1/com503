from cryptography.fernet import Fernet
import base64
import os
from datetime import datetime, timedelta

class TokenManager:
    def __init__(self, secret_key=None):
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

    def encrypt_token(self, token):
        """Encrypt a token string."""
        return self.fernet.encrypt(token.encode()).decode()

    def decrypt_token(self, encrypted_token):
        """Decrypt an encrypted token string."""
        try:
            return self.fernet.decrypt(encrypted_token.encode()).decode()
        except Exception as e:
            print(f"Error decrypting token: {e}")
            return None
