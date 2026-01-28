"""
TTS Client - Google Cloud Chirp 3 HD Text-to-Speech.

Ported from local main_service/app/tts_client.py.
Uses Google Cloud TTS with Chirp 3 HD voices.
"""

import os
import json
import uuid
import base64
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Output directory
AUDIO_OUTPUT_DIR = Path("/app/output/audio")

# Voice name mapping: short name -> full Chirp 3 HD voice name
VOICE_MAP = {
    "Schedar": "en-US-Chirp3-HD-Schedar",
    "Kore": "en-US-Chirp3-HD-Kore",
    "Charon": "en-US-Chirp3-HD-Charon",
    "Fenrir": "en-US-Chirp3-HD-Fenrir",
    "Aoede": "en-US-Chirp3-HD-Aoede",
    "Puck": "en-US-Chirp3-HD-Puck",
    "Leda": "en-US-Chirp3-HD-Leda",
    "Orus": "en-US-Chirp3-HD-Orus",
    "Zephyr": "en-US-Chirp3-HD-Zephyr",
}


def _setup_gcp_credentials():
    """Set up GCP credentials from environment variable (base64 encoded JSON)."""
    gcp_key = os.environ.get('GCP_SERVICE_ACCOUNT_KEY')
    if gcp_key:
        # Decode base64 and write to temp file
        key_path = "/tmp/gcp-sa-key.json"
        try:
            decoded = base64.b64decode(gcp_key)
            with open(key_path, 'wb') as f:
                f.write(decoded)
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = key_path
        except Exception as e:
            logger.warning(f"Failed to decode GCP key: {e}")


# Set up credentials on module load
_setup_gcp_credentials()

# Import GCP TTS after credentials are set
from google.cloud import texttospeech
client = texttospeech.TextToSpeechClient()


async def generate_voiceover(
    text: str,
    voice: str = "Schedar",
    speed: float = 1.0,
    output_filename: str = None
) -> tuple[str, float]:
    """
    Generate voiceover audio using Google Cloud Chirp 3 HD TTS.
    
    Args:
        text: The text to convert to speech
        voice: Voice name (Schedar, Kore, Charon, Fenrir, Aoede, Puck, etc.)
        speed: Playback speed multiplier (1.0 = normal)
        output_filename: Optional filename for the output
        
    Returns:
        Tuple of (audio_file_path, duration_seconds)
    """
    AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    if not output_filename:
        output_filename = f"voiceover_{uuid.uuid4().hex}.wav"
    
    output_path = AUDIO_OUTPUT_DIR / output_filename
    
    # Map short voice name to full Chirp 3 HD name
    full_voice_name = VOICE_MAP.get(voice, f"en-US-Chirp3-HD-{voice}")
    
    logger.info(f"[TTS] Input text length: {len(text)} chars")
    logger.info(f"[TTS] Using voice: {full_voice_name}")
    
    # Apply speed control via SSML if speed != 1.0
    if speed != 1.0:
        rate_percent = int(speed * 100)
        ssml_text = f'<speak><prosody rate="{rate_percent}%">{text}</prosody></speak>'
        input_text = texttospeech.SynthesisInput(ssml=ssml_text)
        logger.info(f"[TTS] Applying speed via SSML: {rate_percent}%")
    else:
        input_text = texttospeech.SynthesisInput(text=text)
    
    # Select voice
    voice_params = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name=full_voice_name
    )
    
    # Configure audio output - LINEAR16 for highest quality
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16
    )
    
    # Call the API
    response = client.synthesize_speech(
        input=input_text,
        voice=voice_params,
        audio_config=audio_config
    )
    
    # Write audio to file
    with open(output_path, "wb") as f:
        f.write(response.audio_content)
    
    logger.info(f"[TTS] Audio saved to: {output_path}")
    logger.info(f"[TTS] Audio size: {len(response.audio_content)} bytes")
    
    # Get duration using ffprobe
    duration = await get_audio_duration(str(output_path))
    logger.info(f"[TTS] Duration: {duration}s")
    
    return str(output_path), duration


async def get_audio_duration(audio_path: str) -> float:
    """Get the duration of an audio file using FFprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ],
        capture_output=True,
        text=True
    )
    
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 10.0
