import os
import tempfile
import math
import random
import boto3
from dotenv import load_dotenv
from pydub import AudioSegment

# Load environment variables
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
    """Initializes S3 client targeting Cloudflare R2."""
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto"
    )

def upload_to_r2(local_file_path: str, destination_filename: str) -> str:
    """Uploads an MP3 file to R2 and returns the public CDN URL."""
    s3 = get_s3_client()
    
    s3.upload_file(
        Filename=local_file_path,
        Bucket=R2_BUCKET_NAME,
        Key=destination_filename,
        ExtraArgs={"ContentType": "audio/mpeg"}
    )
    
    clean_domain = R2_PUBLIC_DOMAIN.rstrip("/")
    return f"{clean_domain}/{destination_filename}"

# ==========================================
# PROCEDURAL AUDIO GENERATION ENGINE
# ==========================================
def generate_procedural_drone(duration_sec: int = 15, base_freq: float = 130.81) -> AudioSegment:
    """Generates a rich, layered ambient drone/pad segment using pure math."""
    sample_rate = 44100
    total_samples = sample_rate * duration_sec
    buffer = bytearray()
    
    # Harmonics for a warm, meditative chord structure (Root, Fifth, Octave)
    harmonics = [1.0, 1.5, 2.0, 3.0]
    
    for i in range(total_samples):
        t = i / sample_rate
        sample = 0.0
        
        # Add smooth slow modulation for organic movement
        lfo = math.sin(2 * math.pi * 0.1 * t) * 0.2 + 0.8
        
        for h in harmonics:
            # Sine wave combination with gentle envelope fading
            envelope = min(t / 2.0, 1.0) * min((duration_sec - t) / 2.0, 1.0)
            wave = math.sin(2 * math.pi * (base_freq * h) * t)
            sample += wave * (1.0 / h) * envelope * lfo
            
        # Normalize and convert to 16-bit PCM integer
        sample = max(min(sample / sum([1.0/h for h in harmonics]), 1.0), -1.0)
        int_val = int(sample * 32767)
        buffer.extend(int_val.to_bytes(2, byteorder='little', signed=True))
        
    segment = AudioSegment(
        data=bytes(buffer),
        sample_width=2,
        frame_rate=sample_rate,
        channels=1
    )
    return segment

def generate_and_upload_session(mood_slug: str, session_id: str, duration_minutes: int = 30) -> str:
    """
    Generates procedural audio sequence, crossfades them, and uploads to Cloudflare R2.
    """
    print(f"Synthesizing procedural session for mood: {mood_slug}...")
    
    combined_audio = AudioSegment.empty()
    
    # Build a continuous sequence of 15-second ambient blocks to match desired duration
    total_clips = max(1, int((duration_minutes * 60) / 15))
    
    # Base frequencies mapped to relaxing states (e.g., C3 = 130.81 Hz, G3 = 196.00 Hz)
    frequencies = [130.81, 146.83, 164.81, 196.00, 220.00]
    
    for i in range(min(total_clips, 120)) :  # Safety limit for background execution
        freq = random.choice(frequencies)
        segment = generate_procedural_drone(duration_sec=15, base_freq=freq)
        
        if len(combined_audio) > 0:
            combined_audio = combined_audio.append(segment, crossfade=3000)
        else:
            combined_audio = segment
            
    # Export compressed MP3
    temp_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    combined_audio.export(temp_mp3.name, format="mp3", bitrate="192k")
    
    # Upload to Cloudflare R2
    remote_key = f"sessions/{session_id}.mp3"
    public_url = upload_to_r2(temp_mp3.name, remote_key)
    
    os.remove(temp_mp3.name)
    return public_url
