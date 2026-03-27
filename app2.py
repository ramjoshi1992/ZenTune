import os
import ssl
import httplib2
import traceback
import psycopg2 # Replaced sqlite3 with psycopg2 for persistence
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from googleapiclient.discovery import build

# --- SSL & Environment Setup ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "https://ramjoshi1992.github.io"}})

# Pulls the 'Internal Database URL' from your Render Environment Variables
DB_URL = os.getenv("DATABASE_URL")

# --- Initialize YouTube API ---
api_key = os.getenv("GOOGLE_API_KEY")
http_unverified = httplib2.Http(disable_ssl_certificate_validation=True)
youtube = build('youtube', 'v3', developerKey=api_key, http=http_unverified)

# --- DATABASE LOGIC (PostgreSQL) ---
def get_db_connection():
    # Connects to the Render Postgres instance
    return psycopg2.connect(DB_URL)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # Create tables if they don't exist
    c.execute('CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, last_goal INTEGER DEFAULT 25)')
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (id SERIAL PRIMARY KEY, 
                  user_id TEXT, 
                  mood TEXT, 
                  duration INTEGER DEFAULT 0,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    c.close()
    conn.close()

# Run initialization on app start
init_db()

# --- HELPER ---
def get_search_query(mood):
    mood_map = {
        "focus": "lofi hip hop radio deep focus study",
        "happy": "positive vibes feel good pop hits 2026",
        "kickstart": "uplifting acoustic morning coffee vibes",
        "anxious": "432hz solfeggio frequencies anxiety relief",
        "stressed": "tibetan singing bowls meditation stress",
        "heartbroken": "healing piano ambient for emotional release",
        "unmotivated": "upbeat morning motivation music energy",
        "socially-drained": "soft minimalist ambient for recharging",
        "sleepy": "delta waves deep sleep music no loop",
        "deepwork": "binaural beats alpha waves concentration"
    }
    return mood_map.get(mood.lower(), "calming ambient healing music")

# --- ROUTES ---

@app.route('/auth', methods=['POST'])
def authenticate():
    user_id = request.json.get('user_id', '').strip()
    if not user_id:
        return jsonify({"status": "error", "message": "ID required"}), 400
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE user_id = %s', (user_id,))
    user = c.fetchone()
    
    if not user:
        c.execute('INSERT INTO users (user_id) VALUES (%s)', (user_id,))
        conn.commit()
        msg = "Account created!"
    else:
        msg = "Welcome back!"
    
    c.close()
    conn.close()
    return jsonify({"status": "success", "message": msg, "user_id": user_id})

@app.route('/identify', methods=['POST'])
def identify_song():
    try:
        data = request.json
        mood = data.get('mood', 'focus')
        query = get_search_query(mood)

        search_req = youtube.search().list(
            q=query, 
            part="snippet", 
            type="video", 
            videoCategoryId="10", 
            videoEmbeddable="true", 
            maxResults=5
        )
        res = search_req.execute()

        tracks = [{
            "title": i['snippet']['title'],
            "artist": i['snippet']['channelTitle'],
            "preview_url": f"https://www.youtube.com/embed/{i['id']['videoId']}",
            "external_link": f"https://www.youtube.com/watch?v={i['id']['videoId']}"
        } for i in res.get('items', [])]

        return jsonify({"status": "success", "tracks": tracks})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/stop', methods=['POST'])
def stop_session():
    data = request.json
    uid = data.get('user_id')
    duration_seconds = data.get('duration', 0)
    duration_minutes = round(duration_seconds / 60)
    mood = data.get('mood')

    if not uid:
        return jsonify({"status": "error", "message": "User ID required"}), 400

    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('INSERT INTO history (user_id, mood, duration) VALUES (%s, %s, %s)', 
                  (uid, mood, duration_minutes))
        conn.commit()
        c.close()
        conn.close()
        return jsonify({"status": "success", "message": "Session saved"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/stats/<user_id>', methods=['GET'])
def get_stats(user_id):
    mood_names = {
        "focus": "Focus & Concentration", "happy": "Pure Joy / Upbeat",
        "kickstart": "Morning Kickstart", "anxious": "Relieve Anxiety",
        "stressed": "De-stress & Meditate", "heartbroken": "Emotional Healing",
        "unmotivated": "Energy Boost", "socially-drained": "Social Recharge",
        "sleepy": "Deep Sleep Prep", "deepwork": "Deep Flow"
    }

    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Total Sessions
        c.execute("SELECT COUNT(*) FROM history WHERE user_id=%s", (user_id,))
        total_sessions = c.fetchone()[0] or 0

        # Total Time
        c.execute("SELECT SUM(duration) FROM history WHERE user_id=%s", (user_id,))
        total_minutes = c.fetchone()[0] or 0
        hours, remaining_mins = divmod(total_minutes, 60)
        time_display = f"{hours}h {remaining_mins}m"

        # Dominant Mood
        c.execute("""SELECT mood FROM history WHERE user_id=%s AND mood IS NOT NULL 
                     GROUP BY mood ORDER BY COUNT(mood) DESC LIMIT 1""", (user_id,))
        dom_res = c.fetchone()
        dominant_display = mood_names.get(dom_res[0], dom_res[0]) if dom_res else "Initial Scan"

        # Streak (Distinct days active)
        c.execute("SELECT COUNT(DISTINCT timestamp::date) FROM history WHERE user_id=%s", (user_id,))
        streak_row = c.fetchone()
        streak_display = f"{streak_row[0] if streak_row else 0} Days"

        c.close()
        conn.close()
        return jsonify({
            "total": total_sessions, "total_time": time_display,
            "dominant": dominant_display, "streak": streak_display
        })

    except Exception as e:
        traceback.print_exc() 
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
