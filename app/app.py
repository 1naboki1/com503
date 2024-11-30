from flask import Flask, jsonify, render_template, request
from pymongo import MongoClient
from weather_service import WeatherService
import os
from datetime import datetime
import threading
import time
from logging_config import setup_logger

# Setup logger
logger = setup_logger('app', 'app.log')

app = Flask(__name__)

# Get MongoDB URI from environment variable
mongodb_uri = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/myapp')
try:
    logger.info("Connecting to MongoDB")
    client = MongoClient(mongodb_uri)
    db = client.myapp
    # Test the connection
    client.server_info()
    logger.info("Successfully connected to MongoDB")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {str(e)}")
    raise

# Initialize weather service
weather_service = WeatherService(db)

def update_warnings_periodically():
    logger.info("Starting periodic warning updates")
    while True:
        try:
            logger.info("Running periodic warning update")
            warnings = weather_service.fetch_warnings()
            if warnings:
                weather_service.save_warnings(warnings)
            time.sleep(300)  # Update every 5 minutes
        except Exception as e:
            logger.error(f"Error in periodic update: {str(e)}")
            time.sleep(60)  # Wait a minute before retrying on error

@app.before_request
def log_request_info():
    logger.info(f"Request: {request.method} {request.url}")

@app.after_request
def log_response_info(response):
    logger.info(f"Response: {response.status}")
    return response

@app.route('/')
def home():
    logger.info("Serving home page")
    return render_template('index.html')

@app.route('/api/warnings', methods=['GET'])
def get_warnings():
    try:
        logger.info("Handling request for active warnings")
        warnings = weather_service.get_active_warnings()
        return jsonify(warnings)
    except Exception as e:
        logger.error(f"Error getting warnings: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/warnings/update', methods=['POST'])
def update_warnings():
    try:
        logger.info("Handling manual warning update request")
        warnings = weather_service.fetch_warnings()
        if warnings:
            weather_service.save_warnings(warnings)
            return jsonify({'message': 'Warnings updated successfully'})
        return jsonify({'error': 'Failed to fetch warnings'}), 500
    except Exception as e:
        logger.error(f"Error updating warnings: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    try:
        # Start the background task for periodic updates
        update_thread = threading.Thread(target=update_warnings_periodically)
        update_thread.daemon = True
        update_thread.start()
        logger.info("Started background update thread")
        
        # Start the Flask application
        logger.info("Starting Flask application")
        app.run(host='0.0.0.0', port=5000)
    except Exception as e:
        logger.critical(f"Application failed to start: {str(e)}")
        raise
