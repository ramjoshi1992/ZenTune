import os
import tempfile
import urllib.request
import boto3
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

import replicate
from pydub import AudioSegment

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
# GENERATION ENGINE
# ==========================================
def generate_and_upload_session(mood_slug: str, session_id: str, duration_minutes: int = 30) -> str:
    """
    Generates audio chunks, crossfades them into an MP3, and stores it in Cloudflare R2.
    """
    # Sample 15-second prompts
    prompts = [
        f"{mood_slug} ambient intro, gentle synth textures, sparse grounding drone, relaxed atmosphere",
        f"{mood_slug} core focus state, subtle rhythmic pulse, deep warm sub-bass, sustained flow state"
    ]
    
    combined_audio = AudioSegment.empty()
    
    for i, prompt in enumerate(prompts):
        print(f"Generating clip {i+1}/{len(prompts)}...")
        
        output = replicate.run(
            "meta/musicgen:6715d92ed502c771e703fc41e007d3f224deed08e3e413719d6742c58e9958a6",
            input={
                "prompt": prompt,
                "duration": 15,
                "model_version": "stereo-large"
            }
        )
        
        # Save temp file safely from Replicate output stream
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        
        # Handle string URLs or FileOutput objects cleanly
        if isinstance(output, str):
            urllib.request.urlretrieve(output, temp_file.name)
        else:
            with open(temp_file.name, "wb") as f:
                f.write(output.read())
        
        segment = AudioSegment.from_file(temp_file.name)
        
        # Equal-power crossfade (2000ms = 2s)
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