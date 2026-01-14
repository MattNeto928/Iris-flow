#!/usr/bin/env python3
"""
Test script for Gemini TTS - run outside of Docker to debug audio generation.
This is the exact reference code from Google's documentation.

Usage:
    export GOOGLE_AI_API_KEY="your-api-key"
    python test_tts.py
"""

import mimetypes
import os
import struct
from google import genai
from google.genai import types


def save_binary_file(file_name, data):
    f = open(file_name, "wb")
    f.write(data)
    f.close()
    print(f"File saved to: {file_name}")


def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    """Generates a WAV file header for the given audio data and parameters."""
    parameters = parse_audio_mime_type(mime_type)
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate = parameters["rate"]
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size
    )
    return header + audio_data


def parse_audio_mime_type(mime_type: str) -> dict:
    """Parses bits per sample and rate from an audio MIME type string."""
    bits_per_sample = 16
    rate = 24000

    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate_str = param.split("=", 1)[1]
                rate = int(rate_str)
            except (ValueError, IndexError):
                pass
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except (ValueError, IndexError):
                pass

    return {"bits_per_sample": bits_per_sample, "rate": rate}


def generate():
    # Get API key from environment
    api_key = os.environ.get("GOOGLE_AI_API_KEY")
    if not api_key:
        print("Error: GOOGLE_AI_API_KEY environment variable not set")
        return
    
    client = genai.Client(api_key=api_key)

    model = "gemini-2.5-flash-preview-tts"
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="Hello! This is a test of the Gemini text to speech system."),
            ],
        ),
    ]
    generate_content_config = types.GenerateContentConfig(
        temperature=1,
        response_modalities=["audio"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Kore"
                )
            )
        ),
    )

    print(f"Generating audio with model: {model}")
    print(f"Voice: Kore")
    print("-" * 50)

    file_index = 0
    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=generate_content_config,
    ):
        if (
            chunk.candidates is None
            or chunk.candidates[0].content is None
            or chunk.candidates[0].content.parts is None
        ):
            continue
            
        if chunk.candidates[0].content.parts[0].inline_data and chunk.candidates[0].content.parts[0].inline_data.data:
            file_name = f"test_audio_{file_index}"
            file_index += 1
            inline_data = chunk.candidates[0].content.parts[0].inline_data
            data_buffer = inline_data.data
            
            print(f"Received chunk {file_index}: {len(data_buffer)} bytes")
            print(f"  mime_type: {inline_data.mime_type}")
            
            file_extension = mimetypes.guess_extension(inline_data.mime_type)
            print(f"  guessed extension: {file_extension}")
            
            if file_extension is None:
                file_extension = ".wav"
                data_buffer = convert_to_wav(inline_data.data, inline_data.mime_type)
                print(f"  converted to WAV: {len(data_buffer)} bytes")
            
            save_binary_file(f"{file_name}{file_extension}", data_buffer)
            
            # Apply speed adjustment if needed (manual test simulation)
            speed = 1.15
            output_file = f"{file_name}{file_extension}"
            final_output = f"{file_name}_sped_up{file_extension}"
            
            if speed != 1.0:
                print(f"Applying speed {speed} to {output_file}...")
                import subprocess
                cmd = [
                    "ffmpeg", "-y", "-i", output_file,
                    "-filter:a", f"atempo={speed}",
                    final_output
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"Saved sped-up audio to: {final_output}")
        else:
            if hasattr(chunk, 'text') and chunk.text:
                print(f"Text response: {chunk.text}")

    print("-" * 50)
    print("Done! Check the generated audio files.")


if __name__ == "__main__":
    generate()
