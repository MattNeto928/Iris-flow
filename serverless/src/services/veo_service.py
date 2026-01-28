"""
Veo Service - Gemini Veo 3.1 video generation.

Generates AI video clips from text descriptions.
Ported from local anim_service/app/veo_client.py.
"""

import os
import uuid
import time
import logging
import asyncio
from pathlib import Path
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Initialize client
client = genai.Client(api_key=os.environ.get("GOOGLE_AI_API_KEY"))

# Output directory
VIDEO_OUTPUT_DIR = Path("/app/output/animations")


class VeoService:
    def __init__(self):
        VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(
        self,
        description: str,
        duration: float = 8.0,
        metadata: dict = None
    ) -> str:
        """
        Generate an animation using Gemini Veo 3.0.
        
        Args:
            description: Text description of the animation
            duration: Target duration (Veo supports 4, 6, 8 seconds)
            metadata: Optional style parameters
            
        Returns:
            Path to generated video file
        """
        output_filename = f"animation_{uuid.uuid4().hex}.mp4"
        output_path = VIDEO_OUTPUT_DIR / output_filename
        
        # Build prompt with style guidance
        prompt = self._build_prompt(description, metadata)
        
        # Snap to valid Veo duration (4, 6, or 8 seconds)
        if duration <= 5:
            veo_duration = 4
        elif duration <= 7:
            veo_duration = 6
        else:
            veo_duration = 8
        
        logger.info(f"[Veo] Generating {veo_duration}s animation...")
        
        try:
            # Generate video - 9:16 vertical format
            operation = client.models.generate_videos(
                model="veo-3.0-fast-generate-001",
                prompt=prompt,
                config=types.GenerateVideosConfig(
                    aspect_ratio="9:16",  # Vertical format
                    resolution="720p",
                    duration_seconds=veo_duration,
                ),
            )
            
            # Poll for completion
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._poll_for_completion(operation)
            )
            
            if result and result.generated_videos:
                video = result.generated_videos[0]
                client.files.download(file=video.video)
                video.video.save(str(output_path))
                logger.info(f"[Veo] Video saved: {output_path}")
                return str(output_path)
            else:
                raise RuntimeError("No video generated")
                
        except Exception as e:
            raise RuntimeError(f"Veo generation failed: {str(e)}")
    
    def _build_prompt(self, description: str, metadata: dict = None) -> str:
        """Build prompt with Veritasium-style guidance."""
        style_notes = metadata.get('style', '') if metadata else ''
        
        style_description = """
Style: Clean, minimalist educational animation (Veritasium/3Blue1Brown style).
- Aesthetic: Pastel-like, clip art / vector art style. Clean and flat.
- Design: Focus on clarity over flashiness. Minimalist design.
- Color Palette: Limited palette, deep blues, whites, distinct accent colors.
- Motion: Smooth, simple movements. Not heavily animated.
- Atmosphere: Professional but accessible educational content.
- Format: VERTICAL 9:16 portrait orientation for mobile viewing.
"""
        
        return f"{description}\n\n{style_description}\nAdditional notes: {style_notes}".strip()
    
    def _poll_for_completion(self, operation, timeout: int = 600, interval: int = 10):
        """Poll for video generation completion."""
        start_time = time.time()
        
        while not operation.done:
            if time.time() - start_time > timeout:
                raise TimeoutError("Video generation timed out")
            
            logger.info(f"[Veo] Waiting... ({int(time.time() - start_time)}s)")
            time.sleep(interval)
            operation = client.operations.get(operation)
        
        return operation.result
