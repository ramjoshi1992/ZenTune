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
# MOOD-AWARE SYNTHESIS PARAMETERS
# ==========================================
def get_mood_parameters(mood_slug: str):
    """Maps mood slugs to specific musical keys, base frequencies, and textures."""
    slug = mood_slug.lower()
    
    if "sleep" in slug or "relax" in slug:
        return {
            "base_freqs": [65.41, 98.00, 110.00, 130.81],
            "harmonics": [1.0, 1.5, 2.0],
            "weights": [1.0, 0.4, 0.2],
            "noise_level": 0.01,
            "vibrato_rate": 0.1
        }
    elif "meditat" in slug or "zen" in slug:
        return {
            "base_freqs": [110.00, 164.81, 196.00, 220.00],
            "harmonics": [1.0, 1.33, 1.5, 2.0],
            "weights": [1.0, 0.7, 0.8, 0.3],
            "noise_level": 0.015,
            "vibrato_rate": 0.15
        }
    else:
        return {
            "base_freqs": [130.81, 146.83, 164.81, 196.00],
            "harmonics": [1.0, 1.2, 1.5, 2.0],
            "weights": [1.0, 0.5, 0.6, 0.3],
            "noise_level": 0.02,
            "vibrato_rate": 0.2
        }

# ==========================================
# AUDIO GENERATION ENGINE
# ==========================================
def generate_procedural_drone(duration_sec: int = 15, mood_slug: str = "deepwork", custom_freq: float = None) -> AudioSegment:
    sample_rate = 44100
    t = np.linspace(0, duration_sec, sample_rate * duration_sec, endpoint=False)
    
    params = get_mood_parameters(mood_slug)
    base_freq = custom_freq if custom_freq else random.choice(params["base_freqs"])
    
    wave = np.zeros_like(t)
    for i, (h, w) in enumerate(zip(params["harmonics"], params["weights"])):
        freq = base_freq * h
        vibrato = np.sin(2 * np.pi * (params["vibrato_rate"] + i * 0.03) * t) * 0.4
        wave += np.sin(2 * np.pi * freq * t + vibrato) * w
        
    noise = np.random.normal(0, params["noise_level"], len(t))
    wave += noise
    
    fade_samples = int(sample_rate * 3.0)
    envelope = np.ones_like(t)
    envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
    envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)
    
    wave *= envelope
    wave /= np.max(np.abs(wave))
    
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
    segment_duration_ms = 15000
    crossfade_ms = 2000
    
    effective_step_ms = segment_duration_ms - crossfade_ms
    total_clips = max(1, int((total_target_ms - crossfade_ms) / effective_step_ms))
    
    params = get_mood_parameters(mood_slug)
    base_freqs = params["base_freqs"]
    
    for i in range(total_clips):
        progress = i / total_clips
        if progress < 0.15:
            freq = base_freqs[0]
        elif progress > 0.85:
            freq = base_freqs[0]
        else:
            freq = random.choice(base_freqs)
            
        segment = generate_procedural_drone(duration_sec=15, mood_slug=mood_slug, custom_freq=freq)
        
        if len(combined_audio) > 0:
            combined_audio = combined_audio.append(segment, crossfade=crossfade_ms)
        else:
            combined_audio = segment
            
    if len(combined_audio) > total_target_ms:
        combined_audio = combined_audio[:total_target_ms]
    elif len(combined_audio) < total_target_ms:
        combined_audio += AudioSegment.silent(duration=(total_target_ms - len(combined_audio)))
            
    temp_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    combined_audio.export(temp_mp3.name, format="mp3", bitrate="192k")
    
    remote_key = f"sessions/{session_id}.mp3"
    public_url = upload_to_r2(temp_mp3.name, remote_key)
    
    os.remove(temp_mp3.name)
    return public_url
