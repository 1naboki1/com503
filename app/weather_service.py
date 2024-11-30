import requests
from datetime import datetime, timedelta
import json
from typing import Dict, List
from logging_config import setup_logger

class WeatherService:
    def __init__(self, db):
        self.api_url = 'https://warnungen.zamg.at/wsapp/api/getWarnstatus'
        self.db = db
        self.logger = setup_logger('weather_service', 'weather_service.log')
        # Ensure indexes for better query performance
        self.setup_db_indexes()

    def setup_db_indexes(self):
        """Setup MongoDB indexes for better query performance"""
        try:
            # Index for warning_id
            self.db.current_warnings.create_index("warning_id", unique=True)
            # Index for timestamps
            self.db.current_warnings.create_index([("start_time", 1), ("end_time", 1)])
            # Index for historical data
            self.db.historical_warnings.create_index([("created_at", 1)])
            self.db.historical_warnings.create_index("warning_id")
            self.logger.info("Database indexes created successfully")
        except Exception as e:
            self.logger.error(f"Error creating database indexes: {str(e)}")

    def fetch_warnings(self) -> Dict:
        try:
            self.logger.info("Fetching warnings from ZAMG API")
            response = requests.get(self.api_url, headers={'accept': 'application/json'})
            response.raise_for_status()
            
            warnings = response.json()
            self.logger.info(f"Successfully fetched {len(warnings.get('features', []))} warnings")
            return warnings
        except requests.RequestException as e:
            self.logger.error(f"Error fetching warnings: {str(e)}")
            return None

    def process_warning(self, warning_feature: Dict) -> Dict:
        try:
            properties = warning_feature.get('properties', {})
            warning_id = properties.get('warnid')
            
            warning_types = {
                1: "storm", 2: "rain", 3: "snow", 4: "black_ice",
                5: "thunderstorm", 6: "heat", 7: "cold"
            }
            
            warning_levels = {
                1: "yellow", 2: "orange", 3: "red"
            }
            
            start_time = datetime.fromtimestamp(int(properties.get('start', 0)))
            end_time = datetime.fromtimestamp(int(properties.get('end', 0)))
            
            return {
                'warning_id': warning_id,
                'warning_type': warning_types.get(properties.get('wtype')),
                'warning_level': warning_levels.get(properties.get('wlevel')),
                'start_time': start_time,
                'end_time': end_time,
                'geometry': warning_feature.get('geometry'),
                'municipalities': properties.get('gemeinden', []),
                'raw_data': warning_feature,  # Store raw data for future reference
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }
        except Exception as e:
            self.logger.error(f"Error processing warning: {str(e)}")
            return None

    def save_warnings(self, warnings_data: Dict):
        if not warnings_data or 'features' not in warnings_data:
            self.logger.warning("No valid warnings data to save")
            return
        
        try:
            current_time = datetime.utcnow()
            
            # Process new warnings
            processed_warnings = []
            for feature in warnings_data['features']:
                processed_warning = self.process_warning(feature)
                if processed_warning:
                    processed_warnings.append(processed_warning)
            
            if processed_warnings:
                # Archive existing warnings before updating
                existing_warnings = list(self.db.current_warnings.find({}))
                if existing_warnings:
                    self.db.historical_warnings.insert_many(existing_warnings)
                    self.logger.info(f"Archived {len(existing_warnings)} warnings to historical collection")
                
                # Update current warnings using upsert
                for warning in processed_warnings:
                    self.db.current_warnings.update_one(
                        {'warning_id': warning['warning_id']},
                        {'$set': warning},
                        upsert=True
                    )
                
                self.logger.info(f"Successfully saved {len(processed_warnings)} warnings")
                
                # Clean up old historical data (keep last 30 days)
                cleanup_date = current_time - timedelta(days=30)
                result = self.db.historical_warnings.delete_many({
                    'created_at': {'$lt': cleanup_date}
                })
                self.logger.info(f"Cleaned up {result.deleted_count} old historical warnings")
                
        except Exception as e:
            self.logger.error(f"Error saving warnings to database: {str(e)}")

    def get_active_warnings(self) -> List[Dict]:
        try:
            current_time = datetime.utcnow()
            warnings = list(self.db.current_warnings.find(
                {
                    'start_time': {'$lte': current_time},
                    'end_time': {'$gte': current_time}
                },
                {'_id': 0, 'raw_data': 0}  # Exclude raw data from response
            ))
            self.logger.info(f"Found {len(warnings)} active warnings")
            return warnings
        except Exception as e:
            self.logger.error(f"Error fetching active warnings: {str(e)}")
            return []

    def get_historical_warnings(self, days: int = 7) -> List[Dict]:
        """Retrieve historical warnings for the specified number of days"""
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            warnings = list(self.db.historical_warnings.find(
                {'created_at': {'$gte': start_date}},
                {'_id': 0, 'raw_data': 0}
            ).sort('created_at', -1))
            self.logger.info(f"Retrieved {len(warnings)} historical warnings")
            return warnings
        except Exception as e:
            self.logger.error(f"Error fetching historical warnings: {str(e)}")
            return []
