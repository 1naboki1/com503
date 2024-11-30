from flask import Flask, jsonify
from pymongo import MongoClient
import os

app = Flask(__name__)

# Get MongoDB URI from environment variable
mongodb_uri = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/myapp')
client = MongoClient(mongodb_uri)
db = client.myapp

@app.route('/')
def hello():
    return jsonify({"message": "Hello from Docker!"})

@app.route('/items', methods=['GET'])
def get_items():
    items = list(db.items.find({}, {'_id': False}))
    return jsonify(items)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
