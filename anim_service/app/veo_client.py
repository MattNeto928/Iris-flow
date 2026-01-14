import os
import uuid
import time
import asyncio
from pathlib import Path
from google import genai
from google.genai import types


# Initialize client - default v1beta supports preview models
client = genai.Client(api_key=os.environ.get("GOOGLE_AI_API_KEY"))

VIDEO_OUTPUT_DIR = "/videos/animations"
STYLE_REFERENCE_PATH = "/app/veritasium_anim.webp"


# Removed reference image logic as we are optimizing prompt instead

def build_style_prompt(description: str, metadata: dict = None) -> str:
    """
    Build a prompt that describes the desired animation style.
    Style inspired by Veritasium-style educational animations.
    """
    style_notes = metadata.get('style', '') if metadata else ''
    
    style_description = """
Style: Clean, minimalist educational animation (Veritasium/3Blue1Brown style).
- Aesthetic: Pastel-like, clip art / vector art style. Clean and flat.
- Design: Focus on clarity over flashiness. Minimalist design.
- Color Palette: Limited color palette, featuring deep blues, whites, and distinct accent colors.
- Motion: Smooth, simple movements. Not heavily animated.
- Atmosphere: Professional but accessible educational content.
"""
    
    full_prompt = f"""{description}

{style_description}
Additional style notes: {style_notes}
"""
    return full_prompt.strip()


async def generate_animation(
    description: str,
    duration_seconds: float = 8.0,
    metadata: dict = None
) -> str:
    """
    Generate an animation using Gemini Veo 3.1.
    
    Args:
        description: Text description of the animation to generate
        duration_seconds: Target duration in seconds (Veo supports 5-8 seconds per clip)
        metadata: Additional parameters (style, etc.)
        
    Returns:
        Path to the generated video file
    """
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
    
    output_filename = f"animation_{uuid.uuid4().hex}.mp4"
    output_path = os.path.join(VIDEO_OUTPUT_DIR, output_filename)
    
    # Build the prompt with style guidance
    prompt = build_style_prompt(description, metadata)
    
    try:
        # Veo only supports 4, 6, 8 seconds
        # Snap to nearest valid duration
        if duration_seconds <= 5:
            duration = 4
        elif duration_seconds <= 7:
            duration = 6
        else:
            duration = 8
            
        print(f"[Veo] Snapped duration {duration_seconds}s to {duration}s")
        
        # Set up config
        config_kwargs = {
            "aspect_ratio": "16:9",
            "resolution": "720p",
            "duration_seconds": duration,
        }
        
        # Generate video using Veo 3.1 with proper config
        operation = client.models.generate_videos(
            model="veo-3.0-fast-generate-001",
            prompt=prompt,
            config=types.GenerateVideosConfig(**config_kwargs),
        )
        
        # Poll for completion (run in executor to not block)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: poll_for_completion(operation)
        )
        
        if result and result.generated_videos:
            video = result.generated_videos[0]
            
            # Download the video
            client.files.download(file=video.video)
            video.video.save(output_path)
            
            return output_path
        else:
            raise RuntimeError("No video generated")
            
    except Exception as e:
        raise RuntimeError(f"Veo generation failed: {str(e)}")


def poll_for_completion(operation, timeout: int = 600, interval: int = 10):
    """
    Poll for video generation completion.
    
    Args:
        operation: The generation operation to poll
        timeout: Maximum time to wait in seconds
        interval: Time between polls in seconds
    
    Returns:
        The completed operation result
    """
    start_time = time.time()
    
    while not operation.done:
        if time.time() - start_time > timeout:
            raise TimeoutError("Video generation timed out")
        
        print(f"Waiting for video generation... ({int(time.time() - start_time)}s)")
        time.sleep(interval)
        operation = client.operations.get(operation)
    
    return operation.result


async def generate_animation_with_image(
    description: str,
    image_path: str,
    duration_seconds: float = 8.0,
    metadata: dict = None
) -> str:
    """
    Generate an animation using Veo 3.1 with an image as starting point.
    """
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
    
    output_filename = f"animation_{uuid.uuid4().hex}.mp4"
    output_path = os.path.join(VIDEO_OUTPUT_DIR, output_filename)
    
    prompt = build_style_prompt(description, metadata)
    
    try:
        # Load the image using types.Image
        image = types.Image.from_file(location=image_path)
        
        # Resolution 1080p requires fixed 8s duration for Veo 3.1
        duration = 8

        # Generate video with image input
        operation = client.models.generate_videos(
            model="veo-3.0-fast-generate-001",
            prompt=prompt,
            image=image,
            config=types.GenerateVideosConfig(
                aspect_ratio="16:9",
                resolution="720p",
                duration_seconds=duration,
            ),
        )
        
        # Poll for completion
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: poll_for_completion(operation)
        )
        
        if result and result.generated_videos:
            video = result.generated_videos[0]
            client.files.download(file=video.video)
            video.video.save(output_path)
            return output_path
        else:
            raise RuntimeError("No video generated")
            
    except Exception as e:
        raise RuntimeError(f"Veo generation with image failed: {str(e)}")
