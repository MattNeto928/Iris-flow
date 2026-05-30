"""
Grok Service - Grok Imagine Video generation via fal.ai.

Generates Veritasium-style clip art parallax animations from text descriptions
using the xai/grok-imagine-video/text-to-video model.
"""

import os
import uuid
import logging
import asyncio
from pathlib import Path

import httpx
import fal_client

logger = logging.getLogger(__name__)

# Output directory
VIDEO_OUTPUT_DIR = Path("/app/output/animations")


class GrokService:
    def __init__(self):
        VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        description: str,
        duration: float = 6.0,
        metadata: dict = None
    ) -> str:
        """
        Generate a clip art parallax animation using Grok Imagine Video.

        Args:
            description: Text description of the animation
            duration: Target duration in seconds (1-15)
            metadata: Optional style parameters

        Returns:
            Path to generated video file
        """
        output_filename = f"grok_{uuid.uuid4().hex}.mp4"
        output_path = VIDEO_OUTPUT_DIR / output_filename

        prompt = self._build_prompt(description, metadata)

        # Clamp duration to API range (1-15 seconds)
        grok_duration = max(1, min(15, int(round(duration))))

        logger.info(f"[Grok] Generating {grok_duration}s animation...")

        try:
            result = await fal_client.subscribe_async(
                "xai/grok-imagine-video/text-to-video",
                arguments={
                    "prompt": prompt,
                    "duration": grok_duration,
                    "aspect_ratio": "9:16",
                    "resolution": "720p",
                },
                with_logs=True,
                on_queue_update=self._on_queue_update,
            )

            video_url = result["video"]["url"]
            logger.info(f"[Grok] Video generated, downloading from {video_url}")

            # Download video
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.get(video_url)
                response.raise_for_status()
                output_path.write_bytes(response.content)

            logger.info(f"[Grok] Video saved: {output_path}")
            return str(output_path)

        except Exception as e:
            raise RuntimeError(f"Grok generation failed: {str(e)}")

    def _build_prompt(self, description: str, metadata: dict = None) -> str:
        """Build prompt with Veritasium-style clip art parallax style guidance."""
        style_notes = metadata.get("style", "") if metadata else ""

        style_description = """
Style: Veritasium-style clip art parallax animation for educational content.
- Aesthetic: Bold, layered clip art with parallax depth. Multiple distinct layers moving at different speeds to create depth.
- Design: Clean vector-style illustrations with strong outlines. Flat colors with subtle gradients.
- Motion: Smooth parallax camera movement - foreground elements move faster than background. Ken Burns-style zooms and pans.
- Color Palette: Vibrant but harmonious. High contrast for clarity. Deep blues, warm oranges, clean whites.
- Atmosphere: Professional educational content that feels dynamic and cinematic.
- Composition: Layered scene with clear foreground, midground, and background elements.
- Format: VERTICAL 9:16 portrait orientation for mobile viewing.
"""

        return f"{description}\n\n{style_description}\nAdditional notes: {style_notes}".strip()

    @staticmethod
    def _on_queue_update(update):
        """Log queue progress updates."""
        if isinstance(update, fal_client.InProgress):
            for log_entry in update.logs:
                logger.info(f"[Grok] {log_entry['message']}")
