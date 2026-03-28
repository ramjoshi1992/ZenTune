import os
import ssl
import httplib2
import traceback
import psycopg2
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from googleapiclient.discovery import build
# Added for secure password handling
from werkzeug.security import generate_password_hash, check_password_hash

# --- SSL & Environment Setup ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
load_dotenv()

app = Flask(__name__)
# Secure CORS for your GitHub Pages frontend
CORS(app, resources={r"/*": {"origins": "https://ramjoshi1992.github.io"}})

# --- DATABASE LOGIC (PostgreSQL) ---
def get_db_connection():
    # 1. Fetch the URL from Render's environment
    # We use os.environ.get to avoid a hard crash if it's missing
    db_url = os.environ.get('DATABASE_URL')
    
    # 2. Safety Check: If the variable is missing, we stop here with a clear log
    if not db_url:
        print("CRITICAL ERROR: DATABASE_URL is not found in Environment Variables!")
        return None

    # 3. Protocol Fix: SQLAlchemy/psycopg2 requires 'postgresql://'
    # Render often provides 'postgres://', which causes the 'split' error
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    # 4. Connect and return the connection object
    try:
        conn = psycopg2.connect(db_url)
        return conn
    except Exception as e:
        print(f"DATABASE CONNECTION ERROR: {e}")
        return None

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Create the table if it doesn't exist at all
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
    
    # 2. THE SELF-FIX: This adds the column if it's missing from an old table
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;")
    
    conn.commit()
    cur.close()
    conn.close()
    print("Database initialized and migrated.")

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
    user_id = request.json.get('user_id', '').strip()
    password = request.json.get('password', '').strip()
    
    if not user_id or not password:
        return jsonify({"status": "error", "message": "ID and Password required"}), 400
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute('SELECT user_id, password_hash FROM users WHERE user_id = %s', (user_id,))
        user = c.fetchone()
        
        if not user:
            # Create new user with hashed password
            hashed_pw = generate_password_hash(password)
            c.execute('INSERT INTO users (user_id, password_hash) VALUES (%s, %s)', (user_id, hashed_pw))
            conn.commit()
            msg = "Account created!"
            return jsonify({"status": "success", "message": msg, "user_id": user_id})
        
        # Verify existing user password
        stored_hash = user[1]
        if check_password_hash(stored_hash, password):
            return jsonify({"status": "success", "message": "Welcome back!", "user_id": user_id})
        else:
            return jsonify({"status": "error", "message": "Invalid password"}), 401
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        c.close()
        conn.close()

@app.route('/identify', methods=['POST'])
def identify_song():
    FALLBACK_TRACKS = {
        "focus": [{"title": "Lofi Study Beats (Backup)", "artist": "ZenTune", "preview_url": "https://www.youtube.com/embed/jfKfPfyJRdk"}],
        "unmotivated": [{"title": "High Energy Phonk (Backup)", "artist": "ZenTune", "preview_url": "https://www.youtube.com/embed/7NOSDKb0H8M"}],
        "anxious": [{"title": "Deep Healing Ambient (Backup)", "artist": "ZenTune", "preview_url": "https://www.youtube.com/embed/5qap5aO4i9A"}]
    }

    try:
        data = request.json
        mood = data.get('mood', 'focus').lower()
        query = get_search_query(mood)

        http_unverified = httplib2.Http(disable_ssl_certificate_validation=True)
        youtube = build('youtube', 'v3', developerKey=os.getenv("GOOGLE_API_KEY"), http=http_unverified)

        search_req = youtube.search().list(
            q=query, 
            part="snippet", 
            type="video", 
            videoCategoryId="10", 
            videoEmbeddable="true", 
            maxResults=3
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
        error_msg = str(e)
        if "quotaExceeded" in error_msg or "403" in error_msg:
            fallback = FALLBACK_TRACKS.get(mood, FALLBACK_TRACKS["focus"])
            return jsonify({
                "status": "success", 
                "tracks": fallback, 
                "note": "API Quota Limit reached. Using ZenTune backup selection."
            })
        return jsonify({"status": "error", "message": "Search failed"}), 500

@app.route('/stop', methods=['POST'])
def stop_session():
    data = request.json
    uid = data.get('user_id')
    duration_seconds = data.get('duration', 0)
    duration_minutes = round(duration_seconds / 60)
    mood = data.get('mood')

    if not uid:
        return jsonify({"status": "error", "message": "User ID required"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute('INSERT INTO history (user_id, mood, duration) VALUES (%s, %s, %s)', 
                  (uid, mood, duration_minutes))
        conn.commit()
        return jsonify({"status": "success", "message": "Session saved"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        c.close()
        conn.close()

@app.route('/stats/<user_id>', methods=['GET'])
def get_stats(user_id):
    mood_names = {
        "focus": "Focus & Concentration", "happy": "Pure Joy / Upbeat",
        "kickstart": "Morning Kickstart", "anxious": "Relieve Anxiety",
        "stressed": "De-stress & Meditate", "heartbroken": "Emotional Healing",
        "unmotivated": "Energy Boost", "socially-drained": "Social Recharge",
        "sleepy": "Deep Sleep Prep", "deepwork": "Deep Flow"
    }

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM history WHERE user_id=%s", (user_id,))
        total_sessions = c.fetchone()[0] or 0

        c.execute("SELECT SUM(duration) FROM history WHERE user_id=%s", (user_id,))
        total_minutes = c.fetchone()[0] or 0
        hours, remaining_mins = divmod(total_minutes, 60)
        time_display = f"{hours}h {remaining_mins}m"

        c.execute("""SELECT mood FROM history WHERE user_id=%s AND mood IS NOT NULL 
                     GROUP BY mood ORDER BY COUNT(mood) DESC LIMIT 1""", (user_id,))
        dom_res = c.fetchone()
        dominant_display = mood_names.get(dom_res[0], dom_res[0]) if dom_res else "Initial Scan"

        c.execute("SELECT COUNT(DISTINCT timestamp::date) FROM history WHERE user_id=%s", (user_id,))
        streak_row = c.fetchone()
        streak_display = f"{streak_row[0] if streak_row else 0} Days"

        return jsonify({
            "total": total_sessions, "total_time": time_display,
            "dominant": dominant_display, "streak": streak_display
        })
    except Exception as e:
        return jsonify({"status": "error", "message": "Could not load stats"}), 500
    finally:
        c.close()
        conn.close()
        
if __name__ == '__main__':
    # Initialize the database ONLY when the app starts up properly
    try:
        print("Starting initialization...")
        init_db()
    except Exception as e:
        print(f"Startup Database Error: {e}")

    # Start the Flask app
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
