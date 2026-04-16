"""
Batch Worker Entrypoint - Routes by JOB_TYPE env var.

JOB_TYPE values: prep, visual, transition, concatenate, postprocess
All jobs read inputs from S3 and write outputs to S3.
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

# Local working directories
OUTPUT_DIR = Path("/app/output")
AUDIO_DIR = OUTPUT_DIR / "audio"
VIDEO_DIR = OUTPUT_DIR / "videos"
COMBINED_DIR = OUTPUT_DIR / "combined"

for d in [AUDIO_DIR, VIDEO_DIR, COMBINED_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ============================================================
# Service registry — maps segment type to (module, class_name)
# ============================================================
SERVICE_MAP = {
    "pysim": ("src.services.pysim_service", "PysimService"),
    "mesa": ("src.services.pysim_service", "PysimService"),
    "pymunk": ("src.services.pysim_service", "PysimService"),
    "manim": ("src.services.manim_service", "ManimService"),
    "animation": ("src.services.veo_service", "VeoService"),
    "simpy": ("src.services.simpy_service", "SimpyService"),
    "plotly": ("src.services.plotly_service", "PlotlyService"),
    "networkx": ("src.services.networkx_service", "NetworkxService"),
    "audio": ("src.services.audio_service", "AudioService"),
    "stats": ("src.services.stats_service", "StatsService"),
    "fractal": ("src.services.fractal_service", "FractalService"),
    "geo": ("src.services.geo_service", "GeoService"),
    "chem": ("src.services.chem_service", "ChemService"),
    "astro": ("src.services.astro_service", "AstroService"),
    "grok": ("src.services.grok_service", "GrokService"),
    "remotion": ("src.services.remotion_service", "RemotionService"),
}


def _get_service(segment_type: str):
    """Lazily import and instantiate a service by segment type."""
    import importlib
    entry = SERVICE_MAP.get(segment_type)
    if not entry:
        raise ValueError(f"Unknown segment type: {segment_type}")
    module_path, class_name = entry
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls()


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

    # Gemini TTS preview: tts_client has built-in retry+backoff for 429 and
    # text-instead-of-audio. TTS_CONCURRENCY env var is an escape hatch if we
    # start tripping rate limits.
    tts_concurrency = int(os.environ.get('TTS_CONCURRENCY', '6'))
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
    metadata = seg.get('metadata', {})

    # Prefix description for mesa/pymunk variants
    if seg_type == "mesa":
        description = f"Agent-based simulation using Mesa library: {description}"
    elif seg_type == "pymunk":
        description = f"2D physics simulation using Pymunk library: {description}"

    # Retry loop with previous_error feedback
    max_retries = 3
    last_error = None
    video_path = None

    for attempt in range(max_retries):
        try:
            service = _get_service(seg_type)

            if seg_type in ("animation", "grok"):
                video_path = await service.generate(
                    description=description,
                    duration=duration,
                    metadata=metadata,
                )
            else:
                video_path = await service.generate(
                    description=description,
                    duration=duration,
                    previous_error=last_error if attempt > 0 else None,
                )

            if not video_path:
                raise RuntimeError(f"Visual generation returned None for {seg_type}")
            break

        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                logger.warning(f"[{video_id}] Visual seg {segment_index} attempt {attempt+1} failed: {e}")
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
# JOB: transition
# ============================================================
async def job_transition():
    """
    Render a single transition segment.
    Downloads manifest + audio + previous segment's lastframe.
    Delegates composition to video_utils.compose_transition (single source of truth).
    """
    from src.video_utils import compose_transition

    video_id = os.environ['VIDEO_ID']
    segment_index = int(os.environ['SEGMENT_INDEX'])

    manifest = _load_manifest(video_id)
    seg = manifest['segments'][segment_index]
    prefix = _s3_key_prefix(video_id)

    # Download audio (required for transitions)
    audio_path = None
    if seg.get('audio_s3_key'):
        audio_path = str(AUDIO_DIR / f"seg_{segment_index:02d}.wav")
        _download(seg['audio_s3_key'], audio_path)

    if not audio_path:
        raise RuntimeError("Transition segment must have voiceover audio")

    duration = seg['duration']

    # Download previous segment's lastframe
    last_frame_path = None
    for j in range(segment_index - 1, -1, -1):
        prev_seg = manifest['segments'][j]
        if prev_seg['type'] != 'transition':
            lf_key = f"{prefix}/segments/seg_{j:02d}_lastframe.png"
            lf_local = str(OUTPUT_DIR / f"prev_lastframe_{video_id}_{segment_index}.png")
            try:
                _download(lf_key, lf_local)
                last_frame_path = lf_local
            except Exception as e:
                logger.warning(f"[{video_id}] Could not download lastframe for seg {j}: {e}")
            break

    # Generate black frame if no last frame available
    if not last_frame_path:
        from PIL import Image
        import numpy as np
        img = Image.fromarray(np.zeros((1920, 1080, 3), dtype=np.uint8))
        last_frame_path = str(OUTPUT_DIR / f"black_frame_{video_id}_{segment_index}.png")
        img.save(last_frame_path)

    output_path = compose_transition(last_frame_path, audio_path, duration, video_id, segment_index)

    _upload(output_path, f"{prefix}/segments/seg_{segment_index:02d}.mp4")
    logger.info(f"[{video_id}] Transition segment {segment_index} complete")


# ============================================================
# JOB: concatenate
# ============================================================
async def job_concatenate():
    """
    Download all segment.mp4 files, crossfade concatenate, add background music.
    Upload final.mp4.
    """
    from src.video_utils import (
        concatenate_videos, add_background_music, get_random_background_music
    )

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

    # Add background music
    try:
        music_path = get_random_background_music(video_id)
        if music_path:
            logger.info(f"[{video_id}] Adding background music...")
            final_path = add_background_music(final_path, music_path, video_id)
    except Exception as e:
        logger.error(f"[{video_id}] Failed to add background music (proceeding without): {e}")

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

    # Generate caption
    logger.info(f"[{video_id}] Generating caption...")
    caption = await generate_caption(prompt)
    youtube_title = prompt[:97] + '...' if len(prompt) > 100 else prompt

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
    "transition": job_transition,
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
