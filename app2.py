from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)

# --- MOCK DATABASE (Replace with SQLAlchemy/PyMongo for production) ---
users_db = {
    "guest": {
        "password": "password123",
        "stats": {"total": 5, "total_time": "2h 30m", "dominant": "Focus", "streak": "3 Days"}
    }
}

# --- 1. REGISTRATION ROUTE ---
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    uid = data.get('user_id', '').strip()
    pwd = data.get('password', '').strip()

    if not uid or not pwd:
        return jsonify({"status": "error", "message": "User ID and Password required"}), 400

    if uid in users_db:
        return jsonify({"status": "error", "message": "User ID already exists"}), 409

    # Create new user profile
    users_db[uid] = {
        "password": pwd,
        "stats": {"total": 0, "total_time": "0h 0m", "dominant": "Initial Scan", "streak": "0 Days"}
    }
    
    return jsonify({"status": "success", "message": "Account created successfully"}), 201

# --- 2. LOGIN ROUTE ---
@app.route('/auth', methods=['POST'])
def auth():
    data = request.json
    uid = data.get('user_id')
    pwd = data.get('password')

    user = users_db.get(uid)
    if user and user['password'] == pwd:
        return jsonify({"status": "success", "user_id": uid}), 200
    
    return jsonify({"status": "error", "message": "Invalid credentials"}), 401

# --- 3. STATS ROUTE (Priority 2 Fix) ---
@app.route('/stats/<user_id>', methods=['GET'])
def get_stats(user_id):
    user = users_db.get(user_id)
    if user:
        return jsonify(user['stats']), 200
    return jsonify({"status": "error", "message": "User not found"}), 404

# --- 4. PASSWORD RESET (Priority 3 Placeholder) ---
@app.route('/reset-password', methods=['POST'])
def reset_password():
    # For now, we return a manual instruction message
    return jsonify({
        "status": "info", 
        "message": "Password reset is currently a manual process. Please contact support@zentune.ai"
    }), 200

# Existing Track Identification Logic
@app.route('/identify', methods=['POST'])
def identify():
    # ... (Your existing track logic remains here) ...
    return jsonify({"status": "success", "tracks": []}) 

if __name__ == '__main__':
    app.run(debug=True, port=5000)
