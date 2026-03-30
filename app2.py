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
from datetime import datetime
from datetime import date, timedelta

# --- SSL & Environment Setup ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
load_dotenv()

app = Flask(__name__)
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
        # Your existing users table is fine
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
        # Updated history table to ensure columns match our logic
        cur.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                mood TEXT,
                duration INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # SELF-HEALING: Check if 'mood' exists in history (if you created it long ago)
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='history' AND column_name='mood';")
        if not cur.fetchone():
            cur.execute("ALTER TABLE history ADD COLUMN mood TEXT;")
            print("Added missing 'mood' column.")

        conn.commit()
        cur.close()
        print("Database initialized successfully.")
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

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    uid = data.get('user_id', '').strip()
    pwd = data.get('password', '').strip()
    if not uid or not pwd:
        return jsonify({"status": "error", "message": "ID and Password required"}), 400
    conn = get_db_connection()
    if not conn: return jsonify({"status": "error", "message": "DB connection failed"}), 500
    try:
        c = conn.cursor()
        c.execute('SELECT user_id FROM users WHERE user_id = %s', (uid,))
        if c.fetchone():
            return jsonify({"status": "error", "message": "User ID taken"}), 409
        hashed_pw = generate_password_hash(pwd)
        c.execute('INSERT INTO users (user_id, password_hash) VALUES (%s, %s)', (uid, hashed_pw))
        conn.commit()
        return jsonify({"status": "success", "message": "Created"}), 201
    finally:
        conn.close()

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
        c.execute('SELECT password_hash FROM users WHERE user_id = %s', (user_id,))
        user = c.fetchone()
        if user and check_password_hash(user[0], password):
            return jsonify({"status": "success", "user_id": user_id})
        return jsonify({"status": "error", "message": "Invalid credentials"}), 401
    finally:
        conn.close()

@app.route('/reset-password', methods=['POST'])
def reset_password():
    return jsonify({"status": "info", "message": "Contact support@zentune.ai"}), 200

@app.route('/identify', methods=['POST'])
def identify_song():
    FALLBACK_TRACKS = [
        {"title": "Lofi Study Beats", "artist": "ZenTune", "preview_url": "https://www.youtube.com/watch?v=jfKfPfyJRdk"},
        {"title": "Ambient Flow", "artist": "ZenTune", "preview_url": "https://www.youtube.com/watch?v=5qap5aO4i9A"},
        {"title": "Deep Focus", "artist": "ZenTune", "preview_url": "https://www.youtube.com/watch?v=DWcJFNfaw9c"}
    ]
    try:
        data = request.json
        mood = data.get('mood', 'focus').lower()
        noise_words = ["instrumental", "ambient", "2026", "new", "relaxing", "mix"]
        query = get_search_query(mood) + " " + random.choice(noise_words)
        api_key = os.environ.get("GOOGLE_API_KEY")
        http_unverified = httplib2.Http(disable_ssl_certificate_validation=True)
        youtube = build('youtube', 'v3', developerKey=api_key, http=http_unverified)
        search_req = youtube.search().list(
            q=query, part="snippet", type="video", videoCategoryId="10", 
            videoEmbeddable="true", maxResults=25, relevanceLanguage="en"
        )
        res = search_req.execute()
        items = res.get('items', [])
        if not items:
            random.shuffle(FALLBACK_TRACKS)
            return jsonify({"status": "success", "tracks": FALLBACK_TRACKS[:3]})
        random.shuffle(items)
        tracks = [{
            "title": i['snippet']['title'],
            "artist": i['snippet']['channelTitle'],
            "preview_url": f"https://www.youtube.com/watch?v={i['id']['videoId']}",
            "external_link": f"https://www.youtube.com/watch?v={i['id']['videoId']}"
        } for i in items[:5]]
        return jsonify({"status": "success", "tracks": tracks})
    except Exception:
        random.shuffle(FALLBACK_TRACKS)
        return jsonify({"status": "success", "tracks": FALLBACK_TRACKS[:3]})

@app.route('/stop', methods=['POST'])
def stop_session():
    data = request.json
    uid = data.get('user_id')
    # Save raw seconds instead of rounding to minutes
    duration_seconds = data.get('duration', 0) 
    mood = data.get('mood')
    conn = get_db_connection()
    if not conn: return jsonify({"status": "error"}), 500
    try:
        c = conn.cursor()
        c.execute('INSERT INTO history (user_id, mood, duration) VALUES (%s, %s, %s)', (uid, mood, duration_seconds))
        conn.commit()
        return jsonify({"status": "success"})
    finally:
        conn.close()

@app.route('/stats/<user_id>', methods=['GET'])
def get_stats(user_id):
    conn = get_db_connection()
    if not conn: 
        return jsonify({"status": "error", "message": "Database connection failed"}), 500
    
    try:
        cur = conn.cursor()
        
        # 1. Get Count and Total Duration
        # Using COALESCE ensures we get 0 instead of None if no history exists
        cur.execute("""
            SELECT COUNT(*), COALESCE(SUM(duration), 0) 
            FROM history 
            WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
        
        total_sessions = row[0] if row else 0
        total_seconds = row[1] if row else 0
        
        # 2. Get the Most Frequent Mood (Dominant Mood)
        cur.execute("""
            SELECT mood FROM history 
            WHERE user_id = %s 
            GROUP BY mood 
            ORDER BY COUNT(*) DESC 
            LIMIT 1
        """, (user_id,))
        mood_row = cur.fetchone()
        dominant = mood_row[0].capitalize() if mood_row and mood_row[0] else "Initial Scan"
        
        # 3. Format Time (Convert seconds to h/m)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        # 4. Calculate Streak (New Logic)
        cur.execute("""
            SELECT DISTINCT date(timestamp) 
            FROM history 
            WHERE user_id = %s 
            ORDER BY date(timestamp) DESC
        """, (user_id,))
        
        dates = [r[0] for r in cur.fetchall()]
        streak = 0
        if dates:
            from datetime import date, timedelta
            today = date.today()
            yesterday = today - timedelta(days=1)
            
            # Start checking from today or yesterday
            # (If they haven't practiced today, the streak might still be alive from yesterday)
            current_check = dates[0]
            if current_check == today or current_check == yesterday:
                streak = 1
                for i in range(len(dates) - 1):
                    # Check if the next date in the list is exactly one day prior
                    if dates[i] - timedelta(days=1) == dates[i+1]:
                        streak += 1
                    else:
                        break
            else:
                streak = 0 # Streak broken (last session was before yesterday)

        return jsonify({
            "total": total_sessions,
            "total_time": f"{hours}h {minutes}m",
            "dominant": dominant,
            "streak": f"{streak} Days"
        }), 200

    except Exception as e:
        print(f"Stats Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/save_session', methods=['POST'])
def save_session():
    data = request.get_json()
    user_id = data.get('user_id')
    duration = data.get('duration')
    mood = data.get('mood')

    if not user_id or user_id == 'guest':
        return jsonify({"status": "ignored"}), 200

    conn = get_db_connection()
    if not conn: return jsonify({"status": "error"}), 500
    
    try:
        cur = conn.cursor()
        # Changed 'created_at' to 'timestamp' to match your existing init_db
        cur.execute("""
            INSERT INTO history (user_id, duration, mood, timestamp) 
            VALUES (%s, %s, %s, now())
        """, (user_id, duration, mood))
        conn.commit()
        return jsonify({"status": "success"}), 201
    except Exception as e:
        print(f"Save Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


init_db()
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
