import os
import ssl
import httplib2
import traceback
import psycopg2
import random
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from googleapiclient.discovery import build
from werkzeug.security import generate_password_hash, check_password_hash

# --- SSL & Environment Setup ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
load_dotenv()

app = Flask(__name__)
# Updated CORS to be more flexible for testing while keeping your domain
CORS(app, resources={r"/*": {"origins": ["https://ramjoshi1992.github.io", "http://127.0.0.1:5500"]}})

# --- DATABASE LOGIC (PostgreSQL) ---
def get_db_connection():
    db_url = os.environ.get('DATABASE_URL') or os.getenv('DATABASE_URL')
    if not db_url:
        return None
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    try:
        return psycopg2.connect(db_url)
    except Exception as e:
        print(f"DATABASE CONNECTION ERROR: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if conn is None: return
    try:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                password_hash TEXT,
                total_sessions INTEGER DEFAULT 0,
                total_time TEXT DEFAULT '0h 0m',
                dominant_mood TEXT DEFAULT 'None',
                streak INTEGER DEFAULT 0,
                last_session_date DATE
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                mood TEXT,
                duration INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"Error during init_db: {e}")
    finally:
        conn.close()

# --- HELPER ---
def get_search_query(mood):
    mood_map = {
        "focus": "lofi hip hop radio deep focus study",
        "happy": "positive vibes feel good pop hits",
        "kickstart": "uplifting acoustic morning coffee vibes",
        "anxious": "432hz solfeggio frequencies anxiety relief",
        "stressed": "tibetan singing bowls meditation stress",
        "heartbroken": "healing piano ambient emotional release",
        "unmotivated": "upbeat morning motivation music energy",
        "socially-drained": "soft minimalist ambient for recharging",
        "sleepy": "delta waves deep sleep music no loop",
        "deepwork": "binaural beats alpha waves concentration"
    }
    return mood_map.get(mood.lower(), "calming ambient healing music")

# --- ROUTES ---

@app.route('/auth', methods=['POST'])
def authenticate():
    data = request.json
    user_id = data.get('user_id', '').strip()
    password = data.get('password', '').strip()
    if not user_id or not password:
        return jsonify({"status": "error", "message": "ID and Password required"}), 400
    conn = get_db_connection()
    if not conn: return jsonify({"status": "error", "message": "Database connection failed"}), 500
    try:
        c = conn.cursor()
        c.execute('SELECT user_id, password_hash FROM users WHERE user_id = %s', (user_id,))
        user = c.fetchone()
        if not user:
            hashed_pw = generate_password_hash(password)
            c.execute('INSERT INTO users (user_id, password_hash) VALUES (%s, %s)', (user_id, hashed_pw))
            conn.commit()
            return jsonify({"status": "success", "message": "Account created!", "user_id": user_id})
        if check_password_hash(user[1], password):
            return jsonify({"status": "success", "message": "Welcome back!", "user_id": user_id})
        else:
            return jsonify({"status": "error", "message": "Invalid password"}), 401
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/identify', methods=['POST'])
def identify_song():
    # Expanded Fallback so it's never "just one song"
    FALLBACK_TRACKS = [
        {"title": "Lofi Study Beats", "artist": "ZenTune", "preview_url": "https://www.youtube.com/watch?v=jfKfPfyJRdk"},
        {"title": "Ambient Flow", "artist": "ZenTune", "preview_url": "https://www.youtube.com/watch?v=5qap5aO4i9A"},
        {"title": "Deep Focus", "artist": "ZenTune", "preview_url": "https://www.youtube.com/watch?v=DWcJFNfaw9c"}
    ]

    try:
        data = request.json
        mood = data.get('mood', 'focus').lower()
        
        # 1. Add a random "noise" word to the query to force different results
        noise_words = ["instrumental", "ambient", "2026", "new", "relaxing", "mix"]
        query = get_search_query(mood) + " " + random.choice(noise_words)
        
        api_key = os.environ.get("GOOGLE_API_KEY")
        http_unverified = httplib2.Http(disable_ssl_certificate_validation=True)
        youtube = build('youtube', 'v3', developerKey=api_key, http=http_unverified)

        # 2. Use 'publishedBefore' or a random 'pageToken' to get different results
        # We'll request 25 items and pick 5 randomly from the whole list
        search_req = youtube.search().list(
            q=query, 
            part="snippet", 
            type="video", 
            videoCategoryId="10", 
            videoEmbeddable="true", 
            maxResults=25,
            relevanceLanguage="en"
        )
        res = search_req.execute()

        items = res.get('items', [])
        if not items:
            random.shuffle(FALLBACK_TRACKS)
            return jsonify({"status": "success", "tracks": FALLBACK_TRACKS[:3]})

        # 3. Shuffle the 25 results and take 5
        random.shuffle(items)
        
        tracks = [{
            "title": i['snippet']['title'],
            "artist": i['snippet']['channelTitle'],
            "preview_url": f"https://www.youtube.com/watch?v={i['id']['videoId']}",
            "external_link": f"https://www.youtube.com/watch?v={i['id']['videoId']}"
        } for i in items[:5]]

        return jsonify({"status": "success", "tracks": tracks})

    except Exception as e:
        print(f"Error: {traceback.format_exc()}")
        random.shuffle(FALLBACK_TRACKS)
        return jsonify({"status": "success", "tracks": FALLBACK_TRACKS[:3], "note": "using_random_fallback"})

@app.route('/stop', methods=['POST'])
def stop_session():
    data = request.json
    uid = data.get('user_id')
    duration_seconds = data.get('duration', 0)
    duration_minutes = round(duration_seconds / 60)
    mood = data.get('mood')
    conn = get_db_connection()
    if not conn: return jsonify({"status": "error", "message": "DB Down"}), 500
    try:
        c = conn.cursor()
        c.execute('INSERT INTO history (user_id, mood, duration) VALUES (%s, %s, %s)', 
                  (uid, mood, duration_minutes))
        conn.commit()
        return jsonify({"status": "success", "message": "Session saved"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/stats/<user_id>', methods=['GET'])
def get_stats(user_id):
    conn = get_db_connection()
    if not conn: return jsonify({"status": "error", "message": "DB Down"}), 500
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*), SUM(duration) FROM history WHERE user_id=%s", (user_id,))
        row = c.fetchone()
        total = row[0] or 0
        total_mins = row[1] or 0
        h = total_mins // 60
        m = total_mins % 60
        
        # Get dominant mood
        c.execute("SELECT mood FROM history WHERE user_id=%s GROUP BY mood ORDER BY COUNT(*) DESC LIMIT 1", (user_id,))
        mood_row = c.fetchone()
        dominant = mood_row[0].capitalize() if mood_row else "Initial Scan"

        return jsonify({
            "total": total, 
            "total_time": f"{h}h {m}m", 
            "dominant": dominant, 
            "streak": "0 Days" # Streak logic can be added later
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    init_db()
    # Use Render's PORT or default to 10000
    port = int(os.environ.get("PORT", 10000)) 
    app.run(host='0.0.0.0', port=port)
