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

        # 1. Users Table
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
        
        # 2. History Table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                mood TEXT,
                frequency TEXT,
                duration INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 3. Feedback Table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS feedback (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                rating INTEGER,
                comment TEXT,
                mood_context TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 4. Self-Healing for History Table
        history_cols = ['mood', 'frequency']
        for col in history_cols:
            cur.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'history' AND column_name = %s
            """, (col,))
            if not cur.fetchone():
                cur.execute(f"ALTER TABLE history ADD COLUMN {col} TEXT;")
                print(f"Added to history: {col}")

        # 5. Self-Healing for Feedback Table (Matches index.html logic)
        feedback_cols = ['before_state', 'after_label', 'mood_context']
        for col in feedback_cols:
            cur.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'feedback' AND column_name = %s
            """, (col,))
            if not cur.fetchone():
                cur.execute(f"ALTER TABLE feedback ADD COLUMN {col} TEXT;")
                print(f"Added to feedback: {col}")

        # Commit all changes to the database
        conn.commit()
        print("Database initialized successfully.")

    except Exception as e:
        # This catches errors and prevents the app from crashing silently
        print(f"Error during init_db: {e}")
    
    finally:
        # Crucial for Render: Always close the connection to avoid leaks
        if conn:
            cur.close()
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
    
    cur = conn.cursor()
    try:
        # Default values to prevent NameError
        total_sessions = 0
        total_seconds = 0
        dominant_label = "Initial Scan"
        streak_count = 0

        # 1. Basic Stats
        cur.execute("SELECT COUNT(*), COALESCE(SUM(duration), 0) FROM history WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if row:
            total_sessions, total_seconds = row

        # 2. Most Frequent Mood (Dominant Mood & Core Frequency)
        cur.execute("""
            SELECT mood FROM history 
            WHERE user_id = %s AND mood IS NOT NULL AND mood != ''
            GROUP BY mood ORDER BY COUNT(*) DESC LIMIT 1
        """, (user_id,))
        mood_row = cur.fetchone()
        if mood_row:
            dominant_label = mood_row[0]

        # 3. Format Time
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        # 4. Streak Calculation
        cur.execute("SELECT DISTINCT date(timestamp) FROM history WHERE user_id = %s ORDER BY date(timestamp) DESC", (user_id,))
        dates = [r[0] for r in cur.fetchall()]
        if dates:
            from datetime import date, timedelta
            today, yesterday = date.today(), date.today() - timedelta(days=1)
            if dates[0] == today or dates[0] == yesterday:
                streak_count = 1
                for i in range(len(dates) - 1):
                    if dates[i] - timedelta(days=1) == dates[i+1]:
                        streak_count += 1
                    else: break

        return jsonify({
            "total": total_sessions,
            "total_time": f"{hours}h {minutes}m",
            "dominant": dominant_label,
            "frequency": dominant_label, # This fills your 'Core Frequency' field
            "streak": f"{streak_count} Days"
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

@app.route('/save_feedback', methods=['POST'])
def save_feedback():
    data = request.get_json()
    user_id = data.get('user_id', 'guest')
    rating = data.get('rating')
    comment = data.get('comment')
    mood_context = data.get('mood_context')

    conn = get_db_connection()
    if not conn: 
        return jsonify({"status": "error", "message": "Database connection failed"}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO feedback (user_id, rating, comment, mood_context, timestamp) 
            VALUES (%s, %s, %s, %s, now())
        """, (user_id, rating, comment, mood_context))
        conn.commit()
        return jsonify({"status": "success", "message": "Feedback recorded"}), 201
    except Exception as e:
        print(f"Feedback Save Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/admin/summary', methods=['GET'])
def admin_summary():
    conn = get_db_connection()
    if not conn: return jsonify({"status": "error"}), 500
    cur = conn.cursor()
    try:
        # Get Global Totals
        cur.execute("SELECT COUNT(*), SUM(duration) FROM history")
        total_sessions, total_seconds = cur.fetchone()
        
        # Get Recent Feedback
        # Corrected Fetch: Matches the Arc Dial and Token data
        cur.execute("""
            SELECT user_id, rating, after_label, before_state, mood_context, timestamp 
            FROM feedback 
            ORDER BY timestamp DESC LIMIT 20
        """)
        
        rows = cur.fetchall()
        
        feedback_list = []
        for r in rows:
            feedback_list.append({
                "user": r[0], 
                "score": r[1],   # The 0-100 Intensity
                "label": r[2],   # The 'Flowing/Settled' label
                "before": r[3],  # The 'Scattered/Tired' tokens
                "mood": r[4],    # The initial mood context
                "time": r[5].strftime("%Y-%m-%d %H:%M") if r[5] else "N/A"
            })

        return jsonify({
            "reflections": feedback_list, 
            "global_sessions": total_sessions or 0, 
            "global_hours": round((total_seconds or 0) / 3600, 1)
        })

    except Exception as e:
        print(f"Admin API Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/health')
def health_check():
    return jsonify({"status": "online"}), 200

if __name__ == "__main__":
    app.run(debug=True)


init_db()
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
