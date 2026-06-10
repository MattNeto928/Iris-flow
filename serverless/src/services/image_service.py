"""
Image Service — Gemini 3.1 Flash Image generation for the storytelling pipeline.

Generates one minimalist clip-art illustration per story beat at 9:16. Two levers
keep the whole video visually consistent:

  1. STYLE ANCHOR — a per-video paragraph (from story_client) prepended to every
     prompt verbatim. Locks medium, palette, characters, framing.
  2. REFERENCE-IMAGE CHAINING — the previously rendered frame is passed back as an
     input image with an explicit "keep the exact same style/characters/world"
     instruction. This is what makes the scientist, stage, palette and creatures
     carry identically across frames (verified against gemini-3.1-flash-image).

Public surface:
    ImageService().generate(image_prompt, style_anchor, out_path, reference_image_path=None)
      -> path to a PNG (9:16). Raises on hard failure after retries.
"""

import os
import asyncio
import logging
from pathlib import Path

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

MODEL_ID = "gemini-3.1-flash-image"
ASPECT_RATIO = "9:16"

# gemini-3.1-flash-image returns ~768x1376 for 9:16; the video step scales/crops
# to 1080x1920, so we do not upscale here.
GEN_TIMEOUT_SEC = 120
MAX_ATTEMPTS = 4

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        key = os.environ.get("GOOGLE_AI_API_KEY")
        if not key:
            raise RuntimeError("GOOGLE_AI_API_KEY environment variable not set")
        _client = genai.Client(api_key=key)
    return _client


def _build_config() -> types.GenerateContentConfig:
    """9:16 image output. Falls back gracefully if the SDK lacks ImageConfig."""
    kwargs = {"response_modalities": ["IMAGE"]}
    try:
        kwargs["image_config"] = types.ImageConfig(aspect_ratio=ASPECT_RATIO)
    except Exception:
        logger.warning("[Image] ImageConfig unavailable in this SDK; relying on prompt aspect cues")
    return types.GenerateContentConfig(**kwargs)


def _extract_image_bytes(response) -> bytes | None:
    for cand in (response.candidates or []):
        parts = (cand.content.parts if cand.content else None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data
    return None


# Transient error markers worth a retry-with-backoff (quota, server hiccups).
_TRANSIENT = (
    "429", "resource_exhausted", "rate", "quota",
    "500", "502", "503", "504",
    "deadline", "unavailable", "internal", "server error",
)


class ImageService:
    def __init__(self):
        pass

    async def generate(
        self,
        image_prompt: str,
        style_anchor: str,
        out_path: str,
        reference_image_path: str | None = None,
    ) -> str:
        """
        Render one illustration to out_path (PNG, 9:16).

        Args:
            image_prompt:           per-beat director's note (no style anchor).
            style_anchor:           per-video style paragraph, prepended verbatim.
            out_path:               where to write the PNG.
            reference_image_path:   previous frame for continuity (optional).
        """
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        client = _get_client()
        config = _build_config()

        full_prompt = (
            f"{style_anchor}\n\n"
            f"Illustrate this single frame in exactly that style: {image_prompt}\n\n"
            f"Vertical 9:16 composition. Absolutely no text, words, letters, numbers, "
            f"captions, or speech bubbles anywhere in the image."
        )

        # Build the contents list. With a reference frame, lead with the image and
        # an explicit continuity instruction so the model treats it as the canon.
        ref_bytes = None
        if reference_image_path and Path(reference_image_path).exists():
            try:
                ref_bytes = Path(reference_image_path).read_bytes()
            except Exception as e:
                logger.warning(f"[Image] could not read reference {reference_image_path}: {e}")

        def _contents(use_ref: bool):
            if use_ref and ref_bytes:
                return [
                    types.Part.from_bytes(data=ref_bytes, mime_type="image/png"),
                    "Use the attached image as the canonical reference. Keep the EXACT "
                    "same art style, line weight, color palette, characters, and world. "
                    "Only change the action/scene as described.\n\n" + full_prompt,
                ]
            return [full_prompt]

        last_err = None
        for attempt in range(MAX_ATTEMPTS):
            # On the final attempt, drop the reference image — occasionally a bad
            # reference makes the model refuse; a clean text-only call recovers.
            use_ref = attempt < MAX_ATTEMPTS - 1
            contents = _contents(use_ref)

            def _sync_call():
                return client.models.generate_content(
                    model=MODEL_ID, contents=contents, config=config
                )

            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(_sync_call), timeout=GEN_TIMEOUT_SEC
                )
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                transient = isinstance(e, asyncio.TimeoutError) or any(t in msg for t in _TRANSIENT)
                wait = min(40.0, (2 ** attempt) * 2)
                logger.warning(
                    f"[Image] attempt {attempt + 1}/{MAX_ATTEMPTS} error "
                    f"({'transient' if transient else 'hard'}): {e}"
                )
                if not transient and attempt < MAX_ATTEMPTS - 1:
                    # Hard error but still retry once or twice without the reference.
                    await asyncio.sleep(1.0)
                    continue
                await asyncio.sleep(wait)
                continue

            img = _extract_image_bytes(response)
            if img:
                Path(out_path).write_bytes(img)
                logger.info(
                    f"[Image] wrote {out_path} ({len(img)} bytes, ref={'yes' if use_ref and ref_bytes else 'no'})"
                )
                return out_path

            # No image part — surface any text (often a safety refusal) and retry.
            text_preview = ""
            try:
                text_preview = (response.text or "")[:200]
            except Exception:
                pass
            last_err = RuntimeError(f"No image returned. Text: {text_preview!r}")
            logger.warning(f"[Image] attempt {attempt + 1}: {last_err}")
            await asyncio.sleep(min(20.0, (2 ** attempt)))

        raise RuntimeError(f"Image generation failed after {MAX_ATTEMPTS} attempts: {last_err}")
