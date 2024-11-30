from flask import Flask, jsonify, render_template, url_for, redirect, request, session, flash
from pymongo import MongoClient
from weather_service import WeatherService
from auth_config import *
import os
from datetime import datetime, timedelta
import threading
import time
from logging_config import setup_logger, log_to_file
from oauthlib.oauth2 import WebApplicationClient
import requests
from functools import wraps
import json

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

    # OAuth 2 client setup
    client = WebApplicationClient(GOOGLE_CLIENT_ID)

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

    # Initialize weather service
    weather_service = WeatherService(db)

    def login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function

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
                authorization_response=request.url,
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
            
            client.parse_request_body_response(token_response.text)
            
            userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
            uri, headers, body = client.add_token(userinfo_endpoint)
            userinfo_response = requests.get(uri, headers=headers)
            userinfo = userinfo_response.json()
            
            if userinfo.get("email_verified"):
                user_data = {
                    'id': userinfo["sub"],
                    'email': userinfo["email"],
                    'name': userinfo.get("given_name", "User")
                }
                
                session['user'] = user_data
                
                # Update database
                db.users.update_one(
                    {'google_id': user_data['id']},
                    {
                        '$set': {
                            'email': user_data['email'],
                            'name': user_data['name'],
                            'last_login': datetime.utcnow()
                        }
                    },
                    upsert=True
                )
                
                return redirect(url_for('home'))
            else:
                return "Email not verified by Google.", 400
                
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return "Login failed.", 500

    @app.route('/logout')
    def logout():
        """Handle logout"""
        session.clear()
        return redirect(url_for('home'))

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

    # Start background task if not in debug mode or if we are in the main thread
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        update_thread = threading.Thread(target=update_warnings_periodically, daemon=True)
        update_thread.start()
        logger.info("Started background warning update thread")

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000)
