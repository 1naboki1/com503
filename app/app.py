from flask import Flask, jsonify, render_template, url_for, redirect, request, session, flash
from pymongo import MongoClient
from weather_service import WeatherService
from auth_config import *
from token_manager import TokenManager
import os
from datetime import datetime, timedelta
import threading
import time
from logging_config import setup_logger, log_to_file
from oauthlib.oauth2 import WebApplicationClient
import requests
from functools import wraps
import json
import secrets

# Initialize logging
logger = setup_logger('app', 'app.log')

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24)

    # Add ProxyFix middleware
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(
        app.wsgi_app, 
        x_for=1,
        x_proto=1,
        x_host=1,
        x_prefix=1
    )

    # Apply session configuration
    app.config.update(
        SESSION_COOKIE_NAME=SESSION_COOKIE_NAME,
        PERMANENT_SESSION_LIFETIME=PERMANENT_SESSION_LIFETIME,
        SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
        SESSION_COOKIE_HTTPONLY=SESSION_COOKIE_HTTPONLY,
        SESSION_COOKIE_SAMESITE=SESSION_COOKIE_SAMESITE
    )

    # Allow insecure transport in development
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

    # MongoDB setup
    try:
        mongodb_uri = os.environ.get('MONGODB_URI')
        if not mongodb_uri:
            logger.critical("MongoDB URI not provided in environment variables")
            raise ValueError("MongoDB URI is required")
            
        db_client = MongoClient(mongodb_uri)
        db = db_client.myapp
        # Test connection
        db_client.admin.command('ping')
        logger.info("Successfully connected to MongoDB")
    except Exception as e:
        logger.critical(f"Failed to connect to MongoDB: {str(e)}")
        raise

    # Initialize token manager
    token_manager = TokenManager(
        logger=logger,  # Pass the already initialized logger
        secret_key=os.environ.get('ENCRYPTION_KEY')
    )

    # Start token refresh thread
    google_config = {
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET
    }
    token_manager.start_token_refresh_thread(db, google_config)

    # Add a cleanup function
    @app.teardown_appcontext
    def cleanup(error):
        """Cleanup resources"""
        token_manager.stop_token_refresh_thread()

    # OAuth 2 client setup
    client = WebApplicationClient(GOOGLE_CLIENT_ID)

    # Initialize weather service
    weather_service = WeatherService(db)

    def login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth_result = is_authenticated()
            logger.info(f"Auth check for {request.path}: {auth_result}")
            if not auth_result:
                logger.info(f"User not authenticated, redirecting to login. Session data: {session.get('user')}")
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function

    def is_authenticated():
        """Check if user is authenticated"""
        if 'user' not in session:
            logger.info("No user in session")
            return False
        
        user = db.users.find_one({
            'google_id': session['user']['id'],
            'session_token': session['user'].get('session_token')
        })
        
        logger.info(f"Authentication check result: {user is not None}")
        return user is not None

    def get_google_provider_cfg():
        try:
            return requests.get(GOOGLE_DISCOVERY_URL).json()
        except Exception as e:
            logger.error(f"Error fetching Google provider config: {str(e)}")
            return None

    def update_warnings_periodically():
        """Background task to update warnings"""
        logger.info("Starting periodic warning updates thread")
        retry_delay = 60  # Initial retry delay of 1 minute
        max_retry_delay = 300  # Maximum retry delay of 5 minutes
        
        while True:
            try:
                start_time = datetime.utcnow()
                logger.info(f"Running periodic warning update at {start_time}")
                
                warnings = weather_service.fetch_warnings()
                if warnings:
                    save_result = weather_service.save_warnings(warnings)
                    if save_result:
                        logger.info(f"Successfully updated warnings at {datetime.utcnow()}")
                        retry_delay = 60  # Reset retry delay after successful update
                    else:
                        logger.error("Failed to save warnings to database")
                else:
                    logger.warning("No warnings received from ZAMG API")
                
                # Calculate processing time and adjust sleep accordingly
                processing_time = (datetime.utcnow() - start_time).total_seconds()
                sleep_time = max(0, 300 - processing_time)  # Ensure 5-minute intervals
                logger.info(f"Sleeping for {sleep_time} seconds until next update")
                time.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"Error in periodic update at {datetime.utcnow()}: {str(e)}")
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)  # Exponential backoff

    @app.before_request
    def before_request():
        """Log request info and check session"""
        if request.path.startswith('/static/'):
            return
        log_to_file(logger, f"Request: {request.method} {request.url}")
        session.permanent = True

    @app.after_request
    def after_request(response):
        """Log response info"""
        if not request.path.startswith('/static/'):
            log_to_file(logger, f"Response: {response.status}")
        return response

    @app.route('/login')
    def login():
        """Handle login"""
        google_provider_cfg = get_google_provider_cfg()
        if not google_provider_cfg:
            return "Error fetching Google configuration.", 500

        authorization_endpoint = google_provider_cfg["authorization_endpoint"]
        callback_uri = url_for('callback', _external=True, _scheme='https')
        logger.info(f"Login - Generated callback URI: {callback_uri}")
        
        request_uri = client.prepare_request_uri(
            authorization_endpoint,
            redirect_uri=callback_uri,
            scope=["openid", "email", "profile"],
        )
        logger.info(f"Login - Full authorization request URI: {request_uri}")
        return redirect(request_uri)

    @app.route('/login/callback')
    def callback():
        """Handle Google OAuth callback"""
        try:
            logger.info(f"Callback - Current request URL: {request.url}")
            logger.info(f"Callback - Request headers: {dict(request.headers)}")
            logger.info(f"Callback - Request args: {dict(request.args)}")
            
            code = request.args.get("code")
            google_provider_cfg = get_google_provider_cfg()
            
            token_endpoint = google_provider_cfg["token_endpoint"]
            callback_uri = url_for('callback', _external=True, _scheme='https')
            logger.info(f"Callback - Token request callback URI: {callback_uri}")
            
            token_url, headers, body = client.prepare_token_request(
                token_endpoint,
                authorization_response=request.url.replace('http://', 'https://'),
                redirect_url=callback_uri,
                code=code
            )
            logger.info(f"Callback - Token request URL: {token_url}")
            logger.info(f"Callback - Token request headers: {headers}")
            logger.info(f"Callback - Token request body: {body}")
            
            token_response = requests.post(
                token_url,
                headers=headers,
                data=body,
                auth=(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET),
            )
            logger.info(f"Callback - Token response status: {token_response.status_code}")
            logger.info(f"Callback - Token response: {token_response.text}")
            
            if token_response.status_code != 200:
                logger.error(f"Token request failed: {token_response.text}")
                return "Authentication failed.", 400

            # Parse the tokens
            tokens = token_response.json()
            client.parse_request_body_response(token_response.text)
            
            # Get user info
            userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
            uri, headers, body = client.add_token(userinfo_endpoint)
            userinfo_response = requests.get(uri, headers=headers)
            
            if userinfo_response.status_code != 200:
                logger.error(f"Userinfo request failed: {userinfo_response.text}")
                return "Failed to get user info.", 400

            userinfo = userinfo_response.json()
            logger.info(f"Callback - User info received: {userinfo}")
            
            if userinfo.get("email_verified"):
                refresh_token = tokens.get('refresh_token')
                session_token = secrets.token_urlsafe(32)
                
                user_data = {
                    'google_id': userinfo["sub"],
                    'email': userinfo["email"],
                    'name': userinfo.get("given_name", "User"),
                    'session_token': session_token,
                    'last_login': datetime.utcnow()
                }
                
                if refresh_token:
                    # Encrypt refresh token
                    encrypted_refresh_token = token_manager.encrypt_token(refresh_token)
                    user_data['refresh_token'] = encrypted_refresh_token
                
                # Update or insert user data
                result = db.users.update_one(
                    {'google_id': user_data['google_id']},
                    {
                        '$set': user_data,
                        '$setOnInsert': {
                            'created_at': datetime.utcnow()
                        }
                    },
                    upsert=True
                )
                logger.info(f"Callback - Database update result: {result.modified_count} documents modified")
                
                # Set session data
                session['user'] = {
                    'id': userinfo["sub"],
                    'email': userinfo["email"],
                    'name': userinfo.get("given_name", "User"),
                    'session_token': session_token
                }
                logger.info("Callback - Session data set successfully")
                
                return redirect(url_for('home'))
            else:
                logger.error("Email not verified by Google")
                return "Email not verified by Google.", 400
                
        except Exception as e:
            logger.error(f"Login error: {str(e)}", exc_info=True)
            return "Login failed.", 500

    @app.route('/logout')
    def logout():
        """Handle logout"""
        try:
            if 'user' in session:
                # Invalidate session token in database
                db.users.update_one(
                    {'google_id': session['user']['id']},
                    {'$unset': {'session_token': ""}}
                )
            session.clear()
            return redirect(url_for('login'))
        except Exception as e:
            logger.error(f"Logout error: {str(e)}")
            session.clear()
            return redirect(url_for('login'))

    @app.route('/')
    @login_required
    def home():
        """Render home page"""
        return render_template('index.html', user=session['user'])

    @app.route('/api/warnings')
    @login_required
    def get_warnings():
        """Get active warnings"""
        try:
            warnings = weather_service.get_active_warnings(session['user']['id'])
            return jsonify(warnings)
        except Exception as e:
            logger.error(f"Error getting warnings: {str(e)}")
            return jsonify({'error': 'Internal server error'}), 500

    @app.route('/api/warnings/historical')
    @login_required
    def get_historical_warnings():
        """Get historical warnings"""
        try:
            days = request.args.get('days', default=7, type=int)
            warnings = weather_service.get_historical_warnings(days, session['user']['id'])
            return jsonify(warnings)
        except Exception as e:
            logger.error(f"Error getting historical warnings: {str(e)}")
            return jsonify({'error': 'Internal server error'}), 500

    @app.route('/api/preferences', methods=['GET', 'POST'])
    @login_required
    def handle_preferences():
        """Handle user preferences"""
        try:
            if request.method == 'POST':
                preferences = request.get_json()
                success = weather_service.update_user_preferences(
                    session['user']['id'],
                    preferences
                )
                if success:
                    return jsonify({'message': 'Preferences updated'})
                return jsonify({'error': 'Failed to update preferences'}), 500
                
            # GET request
            prefs = db.user_preferences.find_one(
                {'user_id': session['user']['id']},
                {'_id': 0}
            )
            return jsonify(prefs or {})
            
        except Exception as e:
            logger.error(f"Error handling preferences: {str(e)}")
            return jsonify({'error': 'Internal server error'}), 500

    @app.route('/check-auth')
    def check_auth():
        """Check if user is authenticated and refresh token if needed"""
        if not is_authenticated():
            return jsonify({'authenticated': False}), 401
        return jsonify({'authenticated': True})

    # Start background task if not in debug mode or if we are in the main thread
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        update_thread = threading.Thread(target=update_warnings_periodically, daemon=True)
        update_thread.start()
        logger.info("Started background warning update thread")

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000)
