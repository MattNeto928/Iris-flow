import os
import uuid
import subprocess
from google.cloud import texttospeech


# Initialize client - uses GOOGLE_APPLICATION_CREDENTIALS env var
client = texttospeech.TextToSpeechClient()

# Output directory for audio files
AUDIO_OUTPUT_DIR = "/videos/audio"

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
    os.makedirs(AUDIO_OUTPUT_DIR, exist_ok=True)
    
    if not output_filename:
        output_filename = f"voiceover_{uuid.uuid4().hex}.wav"
    
    output_path = os.path.join(AUDIO_OUTPUT_DIR, output_filename)
    
    # Map short voice name to full Chirp 3 HD name
    full_voice_name = VOICE_MAP.get(voice, f"en-US-Chirp3-HD-{voice}")
    
    print(f"[TTS] Input text length: {len(text)} chars, preview: {text[:100]}...")
    print(f"[TTS] Using voice: {full_voice_name}")
    
    # Apply speed control via SSML if speed != 1.0
    if speed != 1.0:
        # Convert speed multiplier to percentage (1.5 -> 150%, 0.75 -> 75%)
        rate_percent = int(speed * 100)
        ssml_text = f'<speak><prosody rate="{rate_percent}%">{text}</prosody></speak>'
        input_text = texttospeech.SynthesisInput(ssml=ssml_text)
        print(f"[TTS] Applying speed via SSML: {rate_percent}%")
    else:
        input_text = texttospeech.SynthesisInput(text=text)
    
    # Select voice
    voice_params = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name=full_voice_name
    )
    
    # Configure audio output - LINEAR16 for highest quality (uncompressed)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16
    )
    
    # Call the API
    response = client.synthesize_speech(
        input=input_text,
        voice=voice_params,
        audio_config=audio_config
    )
    
    # Write audio directly to file - no streaming chunk reassembly needed!
    with open(output_path, "wb") as f:
        f.write(response.audio_content)
    
    print(f"[TTS] Audio saved to: {output_path}")
    print(f"[TTS] Audio size: {len(response.audio_content)} bytes")
    
    # Get duration from the audio file
    duration = await get_audio_duration(output_path)
    print(f"[TTS] Duration: {duration}s")
    
    return output_path, duration


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
