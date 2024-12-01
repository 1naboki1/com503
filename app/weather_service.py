import requests
from datetime import datetime, timedelta
import json
from typing import Dict, List, Optional
from logging_config import setup_logger
from pymongo.collection import Collection
from pymongo.database import Database
from urllib3.util import Retry
from requests.adapters import HTTPAdapter

class WeatherService:
    def __init__(self, db: Database):
        self.api_url = 'https://warnungen.zamg.at/wsapp/api/getWarnstatus'
        self.db = db
        self.logger = setup_logger('weather_service', 'weather_service.log')
        self.setup_db_indexes()
        self.setup_requests_session()
        self.logger.info(f"WeatherService initialized with API URL: {self.api_url}")

    def setup_requests_session(self) -> None:
        """Setup requests session with retry logic"""
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.logger.info("Requests session configured with retry strategy")

    def fetch_warnings(self) -> Optional[Dict]:
        """Fetch warnings from ZAMG API"""
        try:
            self.logger.info(f"Starting API call to: {self.api_url}")
            
            # Use session for requests with retry logic
            response = self.session.get(
                self.api_url,
                headers={
                    'accept': 'application/json',
                    'user-agent': 'Mozilla/5.0'
                },
                timeout=30
            )
            
            # Detailed logging of the response
            self.logger.info(f"API Response Status Code: {response.status_code}")
            self.logger.info(f"API Response Headers: {dict(response.headers)}")
            
            # Log first part of response content for debugging
            self.logger.debug(f"API Response Content (first 500 chars): {response.text[:500]}")
            
            if response.status_code == 204:
                self.logger.info("No content returned from API (Status 204)")
                return {'features': []}
                
            response.raise_for_status()
            
            try:
                warnings = response.json()
                if self.validate_warnings_format(warnings):
                    self.logger.info(f"Successfully fetched {len(warnings.get('features', []))} warnings")
                    return warnings
                else:
                    self.logger.error("Invalid warnings format received")
                    self.logger.debug(f"Invalid response content: {response.text}")
                    return None
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON decode error: {str(e)}\nResponse content: {response.text[:500]}")
                return None
                
        except requests.ConnectionError as e:
            self.logger.error(f"Connection error while fetching warnings: {str(e)}")
            return None
        except requests.Timeout as e:
            self.logger.error(f"Timeout while fetching warnings: {str(e)}")
            return None
        except requests.RequestException as e:
            self.logger.error(f"Error fetching warnings: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error in fetch_warnings: {str(e)}", exc_info=True)
            return None

    def validate_warnings_format(self, warnings: Dict) -> bool:
        """Validate the format of the warnings response"""
        try:
            if not isinstance(warnings, dict):
                self.logger.error("Warnings response is not a dictionary")
                return False
            
            if 'features' not in warnings:
                self.logger.error("'features' key missing in warnings response")
                return False
                
            if not isinstance(warnings['features'], list):
                self.logger.error("'features' is not a list in warnings response")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating warnings format: {str(e)}")
            return False

    def setup_db_indexes(self) -> None:
        """Setup MongoDB indexes for better query performance"""
        try:
            # Current warnings indexes
            self.db.current_warnings.create_index("warning_id", unique=True)
            self.db.current_warnings.create_index([("start_time", 1), ("end_time", 1)])
            self.db.current_warnings.create_index([("warning_type", 1)])
            self.db.current_warnings.create_index([("warning_level", 1)])
            
            # Historical warnings indexes
            self.db.historical_warnings.create_index([("created_at", 1)])
            self.db.historical_warnings.create_index("warning_id")
            self.db.historical_warnings.create_index([("warning_type", 1)])
            
            # User preferences indexes
            self.db.user_preferences.create_index("user_id", unique=True)
            
            self.logger.info("Database indexes created successfully")
        except Exception as e:
            self.logger.error(f"Error creating database indexes: {str(e)}")
            raise

    def fetch_warnings(self) -> Optional[Dict]:
        """Fetch warnings from ZAMG API"""
        try:
            self.logger.info("Fetching warnings from ZAMG API")
            response = requests.get(
                self.api_url,
                headers={'accept': 'application/json'},
                timeout=10
            )
            response.raise_for_status()
            
            warnings = response.json()
            self.logger.info(f"Successfully fetched {len(warnings.get('features', []))} warnings")
            return warnings
        except requests.RequestException as e:
            self.logger.error(f"Error fetching warnings: {str(e)}")
            return None
        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding JSON response: {str(e)}")
            return None

    def process_warning(self, warning_feature: Dict) -> Optional[Dict]:
        """Process a single warning feature from the API response"""
        try:
            properties = warning_feature.get('properties', {})
            warning_id = properties.get('warnid')
            
            if not warning_id:
                self.logger.warning("Warning ID missing in feature")
                return None
            
            warning_types = {
                1: "storm", 2: "rain", 3: "snow", 4: "black_ice",
                5: "thunderstorm", 6: "heat", 7: "cold"
            }
            
            warning_levels = {
                1: "yellow", 2: "orange", 3: "red"
            }
            
            try:
                start_time = datetime.fromtimestamp(int(properties.get('start', 0)))
                end_time = datetime.fromtimestamp(int(properties.get('end', 0)))
            except (ValueError, TypeError) as e:
                self.logger.error(f"Error processing timestamps for warning {warning_id}: {str(e)}")
                return None
            
            return {
                'warning_id': warning_id,
                'warning_type': warning_types.get(properties.get('wtype')),
                'warning_level': warning_levels.get(properties.get('wlevel')),
                'start_time': start_time,
                'end_time': end_time,
                'geometry': warning_feature.get('geometry'),
                'municipalities': properties.get('gemeinden', []),
                'raw_data': warning_feature,
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }
        except Exception as e:
            self.logger.error(f"Error processing warning: {str(e)}")
            return None

    def save_warnings(self, warnings_data: Dict) -> bool:
        """Save warnings to database and archive old warnings"""
        if not warnings_data or 'features' not in warnings_data:
            self.logger.warning("No valid warnings data to save")
            return False
        
        try:
            current_time = datetime.utcnow()
            
            # Process new warnings
            processed_warnings = []
            for feature in warnings_data['features']:
                processed_warning = self.process_warning(feature)
                if processed_warning:
                    processed_warnings.append(processed_warning)
            
            if processed_warnings:
                # Archive existing warnings
                existing_warnings = list(self.db.current_warnings.find({}))
                if existing_warnings:
                    self.db.historical_warnings.insert_many(existing_warnings)
                    self.logger.info(f"Archived {len(existing_warnings)} warnings")
                
                # Update current warnings
                self.db.current_warnings.delete_many({})  # Clear current warnings
                self.db.current_warnings.insert_many(processed_warnings)
                self.logger.info(f"Saved {len(processed_warnings)} new warnings")
                
                # Clean up old historical data
                cleanup_date = current_time - timedelta(days=30)
                result = self.db.historical_warnings.delete_many({
                    'created_at': {'$lt': cleanup_date}
                })
                self.logger.info(f"Cleaned up {result.deleted_count} old historical warnings")
                
                return True
        except Exception as e:
            self.logger.error(f"Error saving warnings to database: {str(e)}")
            return False
        
        return False

    def get_active_warnings(self, user_id: Optional[str] = None) -> List[Dict]:
        """Get active warnings, optionally filtered by user preferences"""
        try:
            current_time = datetime.utcnow()
            query = {
                'start_time': {'$lte': current_time},
                'end_time': {'$gte': current_time}
            }
            
            # Apply user preferences if user_id is provided
            if user_id:
                user_prefs = self.db.user_preferences.find_one({'user_id': user_id})
                if user_prefs and 'warning_types' in user_prefs:
                    query['warning_type'] = {'$in': user_prefs['warning_types']}
            
            warnings = list(self.db.current_warnings.find(
                query,
                {'_id': 0, 'raw_data': 0}
            ))
            self.logger.info(f"Found {len(warnings)} active warnings")
            return warnings
        except Exception as e:
            self.logger.error(f"Error fetching active warnings: {str(e)}")
            return []

    def get_historical_warnings(self, days: int = 7, user_id: Optional[str] = None) -> List[Dict]:
        """Get historical warnings for the specified number of days"""
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            query = {'created_at': {'$gte': start_date}}
            
            # Apply user preferences if user_id is provided
            if user_id:
                user_prefs = self.db.user_preferences.find_one({'user_id': user_id})
                if user_prefs and 'warning_types' in user_prefs:
                    query['warning_type'] = {'$in': user_prefs['warning_types']}
            
            warnings = list(self.db.historical_warnings.find(
                query,
                {'_id': 0, 'raw_data': 0}
            ).sort('created_at', -1))
            
            self.logger.info(f"Retrieved {len(warnings)} historical warnings")
            return warnings
        except Exception as e:
            self.logger.error(f"Error fetching historical warnings: {str(e)}")
            return []

    def update_user_preferences(self, user_id: str, preferences: Dict) -> bool:
        """Update user preferences for warning types"""
        try:
            self.db.user_preferences.update_one(
                {'user_id': user_id},
                {'$set': {
                    'warning_types': preferences.get('warning_types', []),
                    'updated_at': datetime.utcnow()
                }},
                upsert=True
            )
            self.logger.info(f"Updated preferences for user {user_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error updating user preferences: {str(e)}")
            return False
