import os
import tempfile
import random
import numpy as np
import boto3
from dotenv import load_dotenv
from pydub import AudioSegment

load_dotenv()

# ==========================================
# CONFIGURATION
# ==========================================
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "zentune-sessions")
R2_PUBLIC_DOMAIN = os.getenv("R2_PUBLIC_DOMAIN", "https://pub-fefcc3396a88474693cc19e7780eb61f.r2.dev")

def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto"
    )

def upload_to_r2(local_file_path: str, destination_filename: str) -> str:
    s3 = get_s3_client()
    s3.upload_file(
        Filename=local_file_path,
        Bucket=R2_BUCKET_NAME,
        Key=destination_filename,
        ExtraArgs={"ContentType": "audio/mpeg"}
    )
    return f"{R2_PUBLIC_DOMAIN.rstrip('/')}/{destination_filename}"

# ==========================================
# FAST VECTORIZED AUDIO ENGINE
# ==========================================
def generate_procedural_drone(duration_sec: int = 15, base_freq: float = 130.81) -> AudioSegment:
    """Generates an ambient drone instantly using vectorized NumPy arrays."""
    sample_rate = 44100
    t = np.linspace(0, duration_sec, sample_rate * duration_sec, endpoint=False)
    
    # Harmonics (Root, Fifth, Octave)
    harmonics = [1.0, 1.5, 2.0, 3.0]
    weights = [1.0, 0.5, 0.33, 0.25]
    
    wave = np.zeros_like(t)
    for h, w in zip(harmonics, weights):
        wave += np.sin(2 * np.pi * (base_freq * h) * t) * w
        
    # Apply smooth fade-in and fade-out envelope to prevent clicks
    fade_samples = int(sample_rate * 2.0)
    envelope = np.ones_like(t)
    envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
    envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)
    
    wave *= envelope
    wave /= np.max(np.abs(wave))  # Normalize
    
    # Convert to 16-bit PCM bytes
    audio_int16 = (wave * 32767).astype(np.int16)
    
    return AudioSegment(
        data=audio_int16.tobytes(),
        sample_width=2,
        frame_rate=sample_rate,
        channels=1
    )

def generate_and_upload_session(mood_slug: str, session_id: str, duration_minutes: int = 30) -> str:
    print(f"Synthesizing progressive session for mood: {mood_slug} ({duration_minutes} mins)...")
    combined_audio = AudioSegment.empty()
    
    total_target_ms = duration_minutes * 60 * 1000
    segment_duration_ms = 15000  # 15 seconds per block
    crossfade_ms = 2000          # 2-second smooth crossfade
    
    # Calculate exact number of clips needed accounting for crossfade overlap
    effective_step_ms = segment_duration_ms - crossfade_ms
    total_clips = max(1, int((total_target_ms - crossfade_ms) / effective_step_ms))
    
    params = get_mood_parameters(mood_slug)
    base_freqs = params["base_freqs"]
    
    for i in range(total_clips):
        # Create a musical progression arc based on session phase
        progress = i / total_clips
        if progress < 0.15:
            # Intro: softer, simpler root frequencies
            freq = base_freqs[0]
        elif progress > 0.85:
            # Outro: winding down back to root
            freq = base_freqs[0]
        else:
            # Core: active exploration of mood-based frequencies
            freq = random.choice(base_freqs)
            
        segment = generate_procedural_drone(duration_sec=15, mood_slug=mood_slug, custom_freq=freq)
        
        if len(combined_audio) > 0:
            combined_audio = combined_audio.append(segment, crossfade=crossfade_ms)
        else:
            combined_audio = segment
            
    # Trim or pad precisely to requested duration if minor variance occurs
    if len(combined_audio) > total_target_ms:
        combined_audio = combined_audio[:total_target_ms]
    elif len(combined_audio) < total_target_ms:
        # Pad with silence if slightly short
        combined_audio += AudioSegment.silent(duration=(total_target_ms - len(combined_audio)))
            
    temp_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    combined_audio.export(temp_mp3.name, format="mp3", bitrate="192k")
    
    remote_key = f"sessions/{session_id}.mp3"
    public_url = upload_to_r2(temp_mp3.name, remote_key)
    
    os.remove(temp_mp3.name)
    return public_url
