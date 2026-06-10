"""
Batch Worker Entrypoint - Routes by JOB_TYPE env var.

JOB_TYPE values: prep, visual, concatenate, postprocess
All jobs read inputs from S3 and write outputs to S3.

Segment engines (3 total):
  matplotlib  → PysimService   (physics sims, 3D geometry, particle clouds)
  manim       → ManimService   (equations, LaTeX derivations, ThreeDScene)
  plotly      → PlotlyService  (continuous 3D surfaces, isosurfaces)
  title_card  → inline FFmpeg  (2-3s dark card, no code generation)
"""

import os
import sys
import json
import uuid
import asyncio
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import boto3

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
VIDEO_BUCKET = os.environ.get('VIDEO_BUCKET_NAME')

# PIPELINE selects the content style. "stem" (default) = manim/matplotlib/plotly
# educational segments. "story" = gemini-3.1-flash-image illustrated origin stories.
# Set per Batch job definition in CDK; prep/visual branch on it, concat/postprocess
# are identical for both pipelines.
PIPELINE = os.environ.get('PIPELINE', 'stem')

# Local working directories
OUTPUT_DIR = Path("/app/output")
AUDIO_DIR = OUTPUT_DIR / "audio"
VIDEO_DIR = OUTPUT_DIR / "videos"
COMBINED_DIR = OUTPUT_DIR / "combined"
IMAGE_DIR = OUTPUT_DIR / "images"

for d in [AUDIO_DIR, VIDEO_DIR, COMBINED_DIR, IMAGE_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ============================================================
# Service registry — 3 engines + title_card (inline, no service)
# ============================================================
SERVICE_MAP = {
    "matplotlib": ("src.services.pysim_service", "PysimService"),
    "manim":      ("src.services.manim_service",  "ManimService"),
    "plotly":     ("src.services.plotly_service", "PlotlyService"),
    # "title_card" is handled inline in job_visual — no service needed
}


def _get_service(segment_type: str):
    """Lazily import and instantiate a service by segment type."""
    import importlib
    entry = SERVICE_MAP.get(segment_type)
    if not entry:
        raise ValueError(
            f"Unknown segment type: '{segment_type}'. "
            f"Valid types: {list(SERVICE_MAP.keys())} + title_card (inline)"
        )
    module_path, class_name = entry
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls()


async def _render_title_card(text: str, duration: float, video_id: str, segment_index: int) -> str:
    """
    Render a title card: centered concept label on #0D0D0D background.
    Uses FFmpeg drawtext — no Claude API call, no script generation.

    Args:
        text: The concept name to display (from segment.description).
        duration: Card duration in seconds (typically 2-3s).
    Returns:
        Path to rendered MP4.
    """
    output_path = str(VIDEO_DIR / f"titlecard_{video_id}_{segment_index:02d}.mp4")

    # Escape text for FFmpeg drawtext (single quotes, colons, backslashes)
    safe_text = text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")

    # Prefer Roboto Light; fall back to DejaVu if not present
    font_candidates = [
        "/app/fonts/Roboto-Light.ttf",
        "/usr/share/fonts/truetype/roboto/Roboto-Light.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    font_path = next((p for p in font_candidates if Path(p).exists()), None)
    fontfile_arg = f":fontfile={font_path}" if font_path else ""

    drawtext = (
        f"drawtext=text='{safe_text}'"
        f"{fontfile_arg}"
        f":fontsize=52"
        f":fontcolor=#F5F5F5"
        f":x=(w-text_w)/2"
        f":y=(h-text_h)/2"
        f":line_spacing=12"
    )

    cmd = [
        "ffmpeg", "-y",
        "-t", str(duration),
        "-f", "lavfi",
        "-i", "color=c=0x0D0D0D:s=1080x1920:r=30",
        "-vf", drawtext,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        output_path,
    ]

    logger.info(f"[{video_id}] Rendering title card: '{text}' ({duration}s)")
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"Title card FFmpeg failed: {stderr.decode()}")

    return output_path


def _s3_key_prefix(video_id: str) -> str:
    return f"jobs/{video_id}"


def _upload(local_path: str, s3_key: str):
    """Upload a file to the video bucket."""
    content_type = 'video/mp4' if s3_key.endswith('.mp4') else 'application/octet-stream'
    if s3_key.endswith('.png'):
        content_type = 'image/png'
    elif s3_key.endswith('.json'):
        content_type = 'application/json'
    elif s3_key.endswith('.wav'):
        content_type = 'audio/wav'
    s3.upload_file(local_path, VIDEO_BUCKET, s3_key, ExtraArgs={'ContentType': content_type})
    logger.info(f"Uploaded {local_path} -> s3://{VIDEO_BUCKET}/{s3_key}")


def _download(s3_key: str, local_path: str):
    """Download a file from the video bucket."""
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(VIDEO_BUCKET, s3_key, local_path)
    logger.info(f"Downloaded s3://{VIDEO_BUCKET}/{s3_key} -> {local_path}")


def _load_manifest(video_id: str) -> dict:
    """Download and parse manifest.json for a video_id."""
    local_path = str(OUTPUT_DIR / "manifest.json")
    _download(f"{_s3_key_prefix(video_id)}/manifest.json", local_path)
    with open(local_path) as f:
        return json.load(f)


# ============================================================
# JOB: prep
# ============================================================
async def job_prep():
    """
    Generate segments via Claude + TTS for all segments.
    Uploads audio files + manifest.json to S3.
    """
    if PIPELINE == 'story':
        return await job_prep_story()

    video_id = os.environ['VIDEO_ID']
    topic = os.environ.get('TOPIC')  # JSON string or None
    target_duration = int(os.environ.get('TARGET_DURATION', '90'))

    from src.services.gemini_client import generate_segments_from_prompt
    from src.services.tts_client import generate_voiceover
    from src.topic_manager import TopicManager

    # If no topic provided, generate one
    if not topic:
        topic_manager = TopicManager()
        topic_data = await topic_manager.get_topic()
        prompt = topic_data['prompt']
        category = topic_data.get('category', 'general')
    else:
        topic_data = json.loads(topic)
        prompt = topic_data.get('prompt', topic_data.get('topic', ''))
        category = topic_data.get('category', 'general')

    logger.info(f"[{video_id}] Generating segments from prompt...")
    # default_speed=1.0 (natural). Per-segment speed variation is preserved in
    # gemini_client's normalization — hooks may slow to 0.96, builds may push to 1.12.
    segments, _llm_prompt, _llm_model = await generate_segments_from_prompt(
        prompt=prompt,
        default_voice="Algenib",
        default_speed=1.0,
        target_duration=target_duration
    )
    logger.info(f"[{video_id}] Generated {len(segments)} segments")

    # Parallel TTS for all segments
    logger.info(f"[{video_id}] Generating TTS for all segments...")

    # Gemini TTS preview has tight parallel-call limits. Observed under
    # concurrency=6: silent HTTP-200 empty responses ("throttle"), then 504s.
    # Concurrency=2 is the safe floor for the preview model. tts_client has
    # retry+backoff for 429 and empty-response cases.
    tts_concurrency = int(os.environ.get('TTS_CONCURRENCY', '2'))
    tts_semaphore = asyncio.Semaphore(tts_concurrency)

    async def generate_tts(seg, idx):
        if not seg.voiceover:
            return None, 5.0
        async with tts_semaphore:
            audio_path, duration = await generate_voiceover(
                text=seg.voiceover.text,
                voice=seg.voiceover.voice,
                speed=seg.voiceover.speed
            )
        return audio_path, duration

    tts_results = await asyncio.gather(*[
        generate_tts(seg, i) for i, seg in enumerate(segments)
    ])

    # Build manifest and upload audio
    prefix = _s3_key_prefix(video_id)
    manifest_segments = []

    for i, (seg, (audio_path, duration)) in enumerate(zip(segments, tts_results)):
        audio_s3_key = None
        if audio_path:
            audio_s3_key = f"{prefix}/audio/seg_{i:02d}.wav"
            _upload(audio_path, audio_s3_key)

        seg_data = {
            "index": i,
            "type": seg.type,
            "title": seg.title,
            "description": seg.description,
            "duration": duration,
            "audio_s3_key": audio_s3_key,
            "metadata": seg.metadata or {},
        }
        if seg.voiceover:
            seg_data["voiceover"] = {
                "text": seg.voiceover.text,
                "voice": seg.voiceover.voice,
                "speed": seg.voiceover.speed,
            }
        manifest_segments.append(seg_data)

    manifest = {
        "video_id": video_id,
        "prompt": prompt,
        "category": category,
        "target_duration": target_duration,
        "segments": manifest_segments,
        "created_at": datetime.utcnow().isoformat(),
    }

    manifest_path = str(OUTPUT_DIR / "manifest.json")
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    _upload(manifest_path, f"{prefix}/manifest.json")

    logger.info(f"[{video_id}] Prep complete: {len(manifest_segments)} segments, manifest uploaded")


# ============================================================
# JOB: visual
# ============================================================
async def job_visual():
    """
    Render a single visual segment.
    Downloads manifest + audio, renders visual, combines, extracts last frame.
    Uploads segment.mp4 + lastframe.png.
    """
    if PIPELINE == 'story':
        return await job_visual_story()

    from src.video_utils import (
        get_duration, match_duration, combine_audio_video, extract_last_frame
    )

    video_id = os.environ['VIDEO_ID']
    segment_index = int(os.environ['SEGMENT_INDEX'])

    manifest = _load_manifest(video_id)
    seg = manifest['segments'][segment_index]
    prefix = _s3_key_prefix(video_id)

    # Download audio if present
    audio_path = None
    if seg.get('audio_s3_key'):
        audio_path = str(AUDIO_DIR / f"seg_{segment_index:02d}.wav")
        _download(seg['audio_s3_key'], audio_path)

    duration = seg['duration']
    seg_type = seg['type']
    description = seg['description']
    # Narration text for this segment — passed to the visual generator so on-screen
    # events can be timed to the words (otherwise the visual never sees what is said).
    voiceover_text = (seg.get('voiceover') or {}).get('text')

    # Title cards are rendered inline — no Claude API call needed
    if seg_type == "title_card":
        video_path = await _render_title_card(description, duration, video_id, segment_index)
    else:
        # Retry loop with previous_error feedback for generative engines
        max_retries = 3
        last_error = None
        video_path = None

        for attempt in range(max_retries):
            try:
                service = _get_service(seg_type)
                video_path = await service.generate(
                    description=description,
                    duration=duration,
                    previous_error=last_error if attempt > 0 else None,
                    voiceover_text=voiceover_text,
                )

                if not video_path:
                    raise RuntimeError(f"Visual generation returned None for {seg_type}")
                break

            except Exception as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    logger.warning(
                        f"[{video_id}] Visual seg {segment_index} attempt {attempt+1} failed: {e}"
                    )
                else:
                    raise

    # Match duration
    video_path = match_duration(video_path, duration)

    # Combine audio + video
    if audio_path:
        combined_path = combine_audio_video(video_path, audio_path, video_id, segment_index)
    else:
        combined_path = video_path

    # Extract last frame
    lastframe_path = extract_last_frame(combined_path, video_id, segment_index)

    # Upload results
    _upload(combined_path, f"{prefix}/segments/seg_{segment_index:02d}.mp4")
    _upload(lastframe_path, f"{prefix}/segments/seg_{segment_index:02d}_lastframe.png")

    logger.info(f"[{video_id}] Visual segment {segment_index} complete")


# ============================================================
# JOB: prep (story pipeline)
# ============================================================
async def job_prep_story():
    """
    Story pipeline prep: write the origin-story script (Claude), synthesize all
    voiceovers (same TTS as STEM), and SEQUENTIALLY render one illustration per
    beat with gemini-3.1-flash-image — each frame chained off the previous one for
    visual continuity. Uploads audio + images + manifest.

    Images are rendered here (not in the parallel visual Map) precisely BECAUSE the
    continuity chain is sequential: frame N needs frame N-1 as its reference. The
    visual Map then only composes clips (ffmpeg), so it stays fully parallel.
    """
    video_id = os.environ['VIDEO_ID']
    topic = os.environ.get('TOPIC')  # JSON string or empty
    target_duration = int(os.environ.get('TARGET_DURATION', '75'))

    from src.services.story_client import generate_story
    from src.services.image_service import ImageService
    from src.services.tts_client import generate_voiceover
    from src.story_topic_manager import StoryTopicManager

    if not topic:
        tm = StoryTopicManager()
        topic_data = await tm.get_topic()
        prompt = topic_data['prompt']
        category = topic_data.get('category', 'origin_story')
    else:
        topic_data = json.loads(topic)
        prompt = topic_data.get('prompt', topic_data.get('topic', ''))
        category = topic_data.get('category', 'origin_story')

    logger.info(f"[{video_id}] Generating story script: {prompt[:80]}")
    style_anchor, beats, _model = await generate_story(prompt, target_duration=target_duration)
    logger.info(f"[{video_id}] Story → {len(beats)} beats")

    # --- TTS for all beats (same mechanism + concurrency floor as STEM) ---
    tts_concurrency = int(os.environ.get('TTS_CONCURRENCY', '2'))
    tts_sem = asyncio.Semaphore(tts_concurrency)

    async def gen_tts(beat):
        async with tts_sem:
            return await generate_voiceover(
                text=beat.voiceover.text,
                voice=beat.voiceover.voice,
                speed=beat.voiceover.speed,
            )

    logger.info(f"[{video_id}] Synthesizing {len(beats)} voiceovers...")
    tts_results = await asyncio.gather(*[gen_tts(b) for b in beats])

    # --- Sequential image generation with reference chaining ---
    logger.info(f"[{video_id}] Rendering {len(beats)} illustrations (chained for continuity)...")
    img_service = ImageService()
    image_paths = []
    prev_image = None
    for i, beat in enumerate(beats):
        out = str(IMAGE_DIR / f"beat_{i:02d}.png")
        await img_service.generate(
            image_prompt=beat.image_prompt,
            style_anchor=style_anchor,
            out_path=out,
            reference_image_path=prev_image,
        )
        image_paths.append(out)
        prev_image = out

    # --- Upload + manifest ---
    prefix = _s3_key_prefix(video_id)
    manifest_segments = []
    for i, (beat, (audio_path, duration)) in enumerate(zip(beats, tts_results)):
        audio_s3_key = f"{prefix}/audio/seg_{i:02d}.wav"
        _upload(audio_path, audio_s3_key)
        image_s3_key = f"{prefix}/images/beat_{i:02d}.png"
        _upload(image_paths[i], image_s3_key)
        manifest_segments.append({
            "index": i,
            "type": "story",
            "title": beat.title,
            "description": beat.image_prompt,
            "duration": duration,
            "audio_s3_key": audio_s3_key,
            "image_s3_key": image_s3_key,
            "voiceover": {
                "text": beat.voiceover.text,
                "voice": beat.voiceover.voice,
                "speed": beat.voiceover.speed,
            },
            "metadata": {},
        })

    manifest = {
        "video_id": video_id,
        "pipeline": "story",
        "prompt": prompt,
        "category": category,
        "style_anchor": style_anchor,
        "target_duration": target_duration,
        "segments": manifest_segments,
        "created_at": datetime.utcnow().isoformat(),
    }
    manifest_path = str(OUTPUT_DIR / "manifest.json")
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    _upload(manifest_path, f"{prefix}/manifest.json")
    logger.info(f"[{video_id}] Story prep complete: {len(manifest_segments)} beats")


# ============================================================
# JOB: visual (story pipeline)
# ============================================================
async def job_visual_story():
    """
    Compose one story beat into a clip: download its pre-rendered illustration +
    voiceover, run the eased Ken Burns + audio composer, upload seg.mp4. No code
    generation and no API calls — pure ffmpeg, so the Map fans out fast.

    Unlike the STEM visual job we do NOT extract a last frame: there are no
    transition segments to chain off it, so it would be dead weight (and an
    avoidable failure mode). concatenate only consumes seg_NN.mp4.
    """
    from src.video_utils import compose_story_clip

    video_id = os.environ['VIDEO_ID']
    segment_index = int(os.environ['SEGMENT_INDEX'])

    manifest = _load_manifest(video_id)
    seg = manifest['segments'][segment_index]
    prefix = _s3_key_prefix(video_id)

    audio_path = str(AUDIO_DIR / f"seg_{segment_index:02d}.wav")
    _download(seg['audio_s3_key'], audio_path)

    image_path = str(IMAGE_DIR / f"beat_{segment_index:02d}.png")
    _download(seg['image_s3_key'], image_path)

    clip_path = compose_story_clip(image_path, audio_path, video_id, segment_index)
    _upload(clip_path, f"{prefix}/segments/seg_{segment_index:02d}.mp4")
    logger.info(f"[{video_id}] Story beat {segment_index} composed")


# ============================================================
# JOB: concatenate
# ============================================================
async def job_concatenate():
    """
    Download all segment.mp4 files, crossfade concatenate, add background music.
    Upload final.mp4.
    """
    from src.video_utils import concatenate_videos

    video_id = os.environ['VIDEO_ID']
    manifest = _load_manifest(video_id)
    prefix = _s3_key_prefix(video_id)

    # Download all segment videos in order.
    # FAIL LOUD if any segment is missing — silently skipping produces a final
    # video that's missing content and makes the voiceover jump around, which
    # is worse than no video at all.
    segment_paths = []
    missing = []
    for seg in manifest['segments']:
        idx = seg['index']
        s3_key = f"{prefix}/segments/seg_{idx:02d}.mp4"
        local_path = str(VIDEO_DIR / f"seg_{idx:02d}.mp4")
        try:
            _download(s3_key, local_path)
            segment_paths.append(local_path)
        except Exception as e:
            logger.error(f"[{video_id}] Segment {idx} ({seg.get('type')}) missing: {e}")
            missing.append(idx)

    if missing:
        raise RuntimeError(
            f"Cannot concatenate: {len(missing)}/{len(manifest['segments'])} "
            f"segments missing from S3: indexes {missing}. "
            f"Check upstream VisualMap/TransitionMap jobs for failures."
        )
    if not segment_paths:
        raise RuntimeError("No segments were successfully downloaded")

    logger.info(f"[{video_id}] Concatenating {len(segment_paths)} segments...")
    final_path = concatenate_videos(segment_paths, video_id)

    # NOTE: We no longer bake background music into the MP4 here. Trending
    # audio is now attached at publish time by Metricool (TikTok via
    # `tiktokData.autoAddMusic`; Instagram via manual-publish workflow).
    # See serverless/src/metricool_client.py.

    # Upload final video to jobs prefix and to permanent storage
    _upload(final_path, f"{prefix}/final.mp4")

    s3_key = f"videos/{datetime.now().strftime('%Y/%m/%d')}/{video_id}.mp4"
    _upload(final_path, s3_key)

    video_url = f"https://{VIDEO_BUCKET}.s3.amazonaws.com/{s3_key}"
    logger.info(f"[{video_id}] Final video uploaded: {video_url}")

    # Write output for next step
    output = {"video_url": video_url, "s3_key": s3_key}
    output_path = str(OUTPUT_DIR / "concat_output.json")
    with open(output_path, 'w') as f:
        json.dump(output, f)
    _upload(output_path, f"{prefix}/concat_output.json")


# ============================================================
# JOB: postprocess
# ============================================================
async def job_postprocess():
    """
    Generate caption, schedule to Metricool, record to DynamoDB.
    """
    from src.services.gemini_client import generate_caption
    from src.metricool_client import MetricoolClient
    from src.topic_manager import TopicManager

    video_id = os.environ['VIDEO_ID']
    schedule_time_str = os.environ.get('SCHEDULE_TIME')

    manifest = _load_manifest(video_id)
    prefix = _s3_key_prefix(video_id)
    prompt = manifest['prompt']
    category = manifest.get('category', 'general')

    # Load concat output for video URL
    concat_output_path = str(OUTPUT_DIR / "concat_output.json")
    _download(f"{prefix}/concat_output.json", concat_output_path)
    with open(concat_output_path) as f:
        concat_output = json.load(f)
    video_url = concat_output['video_url']

    # Generate caption + title (single API call, returns {title, caption})
    logger.info(f"[{video_id}] Generating caption + title...")
    cap_data = await generate_caption(prompt)
    caption = cap_data["caption"]
    youtube_title = cap_data["title"][:97]
    logger.info(f"[{video_id}] title='{youtube_title}'  caption_first40='{caption[:40]}'")

    # Schedule to Metricool
    dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'

    if not dry_run and schedule_time_str:
        metricool = MetricoolClient()
        schedule_time = datetime.fromisoformat(schedule_time_str)
        logger.info(f"[{video_id}] Scheduling to Metricool for {schedule_time}...")
        schedule_result = await metricool.schedule_post(
            video_url=video_url,
            caption=caption,
            schedule_time=schedule_time,
            youtube_title=youtube_title,
        )
        for brand_result in schedule_result.get('results', []):
            brand_id = brand_result.get('blog_id')
            if brand_result.get('success'):
                logger.info(
                    f"[{video_id}] Scheduled brand {brand_id} successfully: "
                    f"{brand_result.get('post_id')} (networks={brand_result.get('networks')})"
                )
            else:
                logger.error(
                    f"[{video_id}] Brand {brand_id} scheduling failed: "
                    f"{brand_result.get('error')}"
                )
        if not schedule_result['success']:
            logger.error(f"[{video_id}] Scheduling had failures: {schedule_result.get('error')}")
    else:
        logger.info(f"[{video_id}] Skipping Metricool (dry_run={dry_run})")

    # Record topic to DynamoDB
    topic_manager = TopicManager()
    topic_id = video_id.split('_')[0] if '_' in video_id else video_id
    await topic_manager.record_topic(
        topic_id=topic_id,
        category=category,
        prompt=prompt,
        video_url=video_url,
    )
    logger.info(f"[{video_id}] Postprocess complete")


# ============================================================
# Main dispatcher
# ============================================================
JOB_DISPATCH = {
    "prep": job_prep,
    "visual": job_visual,
    "concatenate": job_concatenate,
    "postprocess": job_postprocess,
}


def main():
    job_type = os.environ.get('JOB_TYPE')
    if not job_type:
        logger.error("JOB_TYPE environment variable not set")
        sys.exit(1)

    handler = JOB_DISPATCH.get(job_type)
    if not handler:
        logger.error(f"Unknown JOB_TYPE: {job_type}. Must be one of: {list(JOB_DISPATCH.keys())}")
        sys.exit(1)

    logger.info(f"Starting worker: JOB_TYPE={job_type}")
    logger.info(f"VIDEO_ID={os.environ.get('VIDEO_ID', 'N/A')}")

    try:
        asyncio.run(handler())
        logger.info(f"Worker {job_type} completed successfully")
    except Exception as e:
        logger.exception(f"Worker {job_type} failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
