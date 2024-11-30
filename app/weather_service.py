import requests
from datetime import datetime
import json
from typing import Dict, List
from logging_config import setup_logger

class WeatherService:
    def __init__(self, db):
        self.api_url = 'https://warnungen.zamg.at/wsapp/api/getWarnstatus'
        self.db = db
        self.logger = setup_logger('weather_service', 'weather_service.log')

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
        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding JSON response: {str(e)}")
            return None

    def process_warning(self, warning_feature: Dict) -> Dict:
        try:
            properties = warning_feature.get('properties', {})
            warning_id = properties.get('warnid')
            self.logger.debug(f"Processing warning {warning_id}")
            
            # Convert warning type to readable format
            warning_types = {
                1: "storm",
                2: "rain",
                3: "snow",
                4: "black_ice",
                5: "thunderstorm",
                6: "heat",
                7: "cold"
            }
            
            # Convert warning level to readable format
            warning_levels = {
                1: "yellow",
                2: "orange",
                3: "red"
            }
            
            # Convert timestamps to datetime
            start_time = datetime.fromtimestamp(int(properties.get('start', 0)))
            end_time = datetime.fromtimestamp(int(properties.get('end', 0)))
            
            processed_warning = {
                'warning_id': warning_id,
                'warning_type': warning_types.get(properties.get('wtype')),
                'warning_level': warning_levels.get(properties.get('wlevel')),
                'start_time': start_time,
                'end_time': end_time,
                'geometry': warning_feature.get('geometry'),
                'municipalities': properties.get('gemeinden', []),
                'created_at': datetime.utcnow()
            }
            
            self.logger.debug(f"Successfully processed warning {warning_id}")
            return processed_warning
            
        except Exception as e:
            self.logger.error(f"Error processing warning: {str(e)}")
            return None

    def save_warnings(self, warnings_data: Dict):
        if not warnings_data or 'features' not in warnings_data:
            self.logger.warning("No valid warnings data to save")
            return
        
        try:
            processed_warnings = []
            for feature in warnings_data['features']:
                processed_warning = self.process_warning(feature)
                if processed_warning:
                    processed_warnings.append(processed_warning)
            
            if processed_warnings:
                # Remove old warnings
                delete_result = self.db.warnings.delete_many({})
                self.logger.info(f"Deleted {delete_result.deleted_count} old warnings")
                
                # Insert new warnings
                insert_result = self.db.warnings.insert_many(processed_warnings)
                self.logger.info(f"Successfully saved {len(insert_result.inserted_ids)} warnings to database")
            else:
                self.logger.warning("No warnings to save after processing")
                
        except Exception as e:
            self.logger.error(f"Error saving warnings to database: {str(e)}")

    def get_active_warnings(self) -> List[Dict]:
        try:
            current_time = datetime.utcnow()
            self.logger.info("Fetching active warnings from database")
            
            warnings = list(self.db.warnings.find(
                {
                    'start_time': {'$lte': current_time},
                    'end_time': {'$gte': current_time}
                },
                {'_id': 0}
            ))
            
            self.logger.info(f"Found {len(warnings)} active warnings")
            return warnings
            
        except Exception as e:
            self.logger.error(f"Error fetching active warnings: {str(e)}")
            return []
