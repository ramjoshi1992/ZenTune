import os
import tempfile
import urllib.request
import boto3
import requests
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

HF_TOKEN = os.getenv("HF_TOKEN")
HF_API_URL = "https://router.huggingface.co/hf-inference/models/facebook/musicgen-small"

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
# GENERATION ENGINE (Hugging Face Free Tier)
# ==========================================
def generate_hf_clip(prompt: str) -> bytes:
    """Sends a request to Hugging Face's free Inference API for MusicGen."""
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {"inputs": prompt}
    
    response = requests.post(HF_API_URL, headers=headers, json=payload)
    
    if response.status_code != 200:
        raise Exception(f"Hugging Face API Error ({response.status_code}): {response.text}")
        
    return response.content

def generate_and_upload_session(mood_slug: str, session_id: str, duration_minutes: int = 30) -> str:
    """
    Generates audio chunks via Hugging Face, crossfades them, and uploads to R2.
    """
    prompts = [
        f"{mood_slug} ambient intro, gentle synth textures, sparse grounding drone, relaxed atmosphere",
        f"{mood_slug} core focus state, subtle rhythmic pulse, deep warm sub-bass, sustained flow state"
    ]
    
    combined_audio = AudioSegment.empty()
    
    for i, prompt in enumerate(prompts):
        print(f"Generating clip {i+1}/{len(prompts)} via Hugging Face...")
        
        audio_bytes = generate_hf_clip(prompt)
        
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        with open(temp_file.name, "wb") as f:
            f.write(audio_bytes)
        
        segment = AudioSegment.from_file(temp_file.name)
        
        if len(combined_audio) > 0:
            combined_audio = combined_audio.append(segment, crossfade=2000)
        else:
            combined_audio = segment
            
        os.remove(temp_file.name)
        
    # Export compressed MP3
    temp_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    combined_audio.export(temp_mp3.name, format="mp3", bitrate="192k")
    
    # Upload to Cloudflare R2
    remote_key = f"sessions/{session_id}.mp3"
    public_url = upload_to_r2(temp_mp3.name, remote_key)
    
    os.remove(temp_mp3.name)
    return public_url
