"""
Video Utilities - Stateless ffmpeg helper functions.

Shared by worker.py (Batch jobs) and local/server.py (dev server).
All functions are pure (no class state) and operate on file paths.
"""

import hashlib
import os
import random
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
MUSIC_BUCKET = os.environ.get('MUSIC_BUCKET_NAME')

# Local working directories
OUTPUT_DIR = Path("/app/output")
AUDIO_DIR = OUTPUT_DIR / "audio"
VIDEO_DIR = OUTPUT_DIR / "videos"
COMBINED_DIR = OUTPUT_DIR / "combined"


def get_duration(path: str) -> float:
    """Get media file duration using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 10.0


def match_duration(video_path: str, target_duration: float) -> str:
    """Time-stretch video to match target duration."""
    video_duration = get_duration(video_path)

    if abs(video_duration - target_duration) < 0.05:
        return video_path

    speed_factor = video_duration / target_duration
    pts_factor = 1 / speed_factor

    output_path = str(Path(video_path).with_suffix('.stretched.mp4'))

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-filter:v", f"setpts={pts_factor}*PTS",
        "-an",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(f"Duration match failed: {result.stderr}")
        return video_path

    return output_path


def combine_audio_video(
    video_path: str,
    audio_path: str,
    video_id: str,
    segment_index: int,
    narration_delay: float = 0.5
) -> str:
    """Combine audio and video into final segment with narration delay."""
    COMBINED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = COMBINED_DIR / f"{video_id}_seg{segment_index}_combined.mp4"

    video_duration = get_duration(video_path)
    audio_duration = get_duration(audio_path)

    # Total audio duration including the silence pad at start
    total_audio = audio_duration + narration_delay
    delay_ms = int(narration_delay * 1000)

    # Always ensure video covers full audio duration to prevent cutoff
    if total_audio > video_duration + 0.05:
        extra = total_audio - video_duration
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex",
            f"[0:v]tpad=stop_mode=clone:stop_duration={extra}[v];"
            f"[1:a]adelay={delay_ms}|{delay_ms}[a]",
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path)
        ]
    else:
        # Video is longer or equal — trim video to match audio
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex",
            f"[1:a]adelay={delay_ms}|{delay_ms}[a]",
            "-map", "0:v:0",
            "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(total_audio),
            str(output_path)
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Audio/video combine failed: {result.stderr}")

    return str(output_path)


def compose_transition(
    last_frame_path: str,
    audio_path: str,
    duration: float,
    video_id: str,
    segment_index: int,
) -> str:
    """Compose a transition segment: subtle Ken Burns over last frame + voiceover.

    No color grade. No fade-to-black. The cross-fade between segments is handled
    later in `concatenate_videos` via xfade + acrossfade, so each transition
    segment is a clean hold-and-drift on the previous segment's final frame.

    Determinism:
      - Alternating zoom-in / zoom-out direction per segment_index keeps
        consecutive transitions from feeling identical.
      - Horizontal pan direction is MD5-seeded by (video_id, segment_index) so
        re-renders match exactly.
    """
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    output_path = VIDEO_DIR / f"{video_id}_seg{segment_index}_transition.mp4"

    FPS = 30
    total_frames = max(int(duration * FPS), 1)

    # Subtle Ken Burns: 3% zoom over the clip. Softer than the previous 6% —
    # short durations (< 3s) with 6% zoom read as a judder.
    MAX_ZOOM = 1.03
    zoom_rate = (MAX_ZOOM - 1.0) / total_frames
    if segment_index % 2 == 0:
        z_expr = f"'min(1.0+on*{zoom_rate:.6f},{MAX_ZOOM})'"      # push in
    else:
        z_expr = f"'max({MAX_ZOOM}-on*{zoom_rate:.6f},1.0)'"      # pull back

    seed_bytes = hashlib.md5(f"{video_id}:{segment_index}".encode()).digest()
    pan_dir = 1 if seed_bytes[0] & 1 else -1
    pan_rate_px = pan_dir * 8.0 / total_frames

    filter_complex = (
        "[0:v]"
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
        "setsar=1,"
        f"zoompan=z={z_expr}:"
        f"x='iw/2-(iw/zoom/2)+on*{pan_rate_px:.6f}':"
        "y='ih/2-(ih/zoom/2)':"
        f"d=1:s=1080x1920:fps={FPS},"
        "format=yuv420p"
        "[outv]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(duration), "-i", last_frame_path,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Transition composition failed: {result.stderr}")

    return str(output_path)


def extract_last_frame(video_path: str, video_id: str, segment_index: int) -> str:
    """Extract the last frame from a video."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"last_frame_{video_id}_{segment_index}.png"

    # Use -sseof to seek from the end (avoids keyframe seek overshoot)
    cmd = [
        "ffmpeg", "-y",
        "-sseof", "-0.1",
        "-i", video_path,
        "-update", "1",
        "-frames:v", "1",
        str(output_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"Frame extraction failed: {result.stderr}")

    return str(output_path)


def _build_xfade_chain(n: int, durations: list[float], xfade_dur: float = 0.3) -> str:
    """
    Build the pairwise xfade + acrossfade portion of the filter_complex.

    Each normalized input is pre-labeled [viN]/[aiN] by the caller. We chain:
      [v0N]+[v1N] -xfade-> [vx1]; [vx1]+[v2N] -xfade-> [vx2]; ...
      [a0N]+[a1N] -acrossfade-> [ax1]; [ax1]+[a2N] -acrossfade-> [ax2]; ...
    The xfade `offset` is cumulative (duration of chain so far minus xfade_dur
    per join), so each new input starts overlapping the last `xfade_dur` seconds.
    """
    parts = []
    cum = 0.0
    for i in range(1, n):
        cum += durations[i - 1] - xfade_dur
        v_in = "[v0N]" if i == 1 else f"[vx{i-1}]"
        a_in = "[a0N]" if i == 1 else f"[ax{i-1}]"
        parts.append(
            f"{v_in}[v{i}N]xfade=transition=fade:duration={xfade_dur:.3f}:"
            f"offset={cum:.3f}[vx{i}]"
        )
        parts.append(
            f"{a_in}[a{i}N]acrossfade=d={xfade_dur:.3f}:c1=tri:c2=tri[ax{i}]"
        )
    return ";".join(parts)


def concatenate_videos(video_paths: list[str], video_id: str) -> str:
    """
    Concatenate with pairwise crossfades + EBU loudness normalization.

    - Each segment is pre-normalized to 1080x1920@30fps yuv420p, 44.1kHz mono.
    - Adjacent segments crossfade over 0.3s (video via xfade, audio via
      acrossfade) — eliminates the black-flash and volume-jump at joins.
    - The final audio stream is run through `loudnorm` (EBU R128, I=-16 LUFS,
      TP=-1.5 dBTP, LRA=11) which is the YouTube/TikTok-safe target for Shorts.
    """
    COMBINED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = COMBINED_DIR / f"{video_id}_final.mp4"

    if len(video_paths) == 1:
        shutil.copy(video_paths[0], output_path)
        return str(output_path)

    width, height = 1080, 1920
    fps = 30
    xfade_dur = 0.3

    # Per-input durations drive xfade offsets.
    durations = [get_duration(p) for p in video_paths]

    # Guard: xfade requires each segment's duration > xfade_dur.
    if any(d <= xfade_dur for d in durations):
        logger.warning(
            f"[{video_id}] Segment shorter than xfade_dur ({xfade_dur}s): "
            f"durations={durations} — falling back to plain concat"
        )
        return _plain_concat(video_paths, video_id, width, height, fps)

    input_args = []
    for path in video_paths:
        input_args.extend(["-i", path])

    # Pre-normalize every input into [viN]/[aiN].
    filter_parts = []
    for i in range(len(video_paths)):
        filter_parts.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={fps},setsar=1,format=yuv420p[v{i}N]"
        )
        filter_parts.append(
            f"[{i}:a]aresample=44100,"
            f"aformat=sample_fmts=fltp:channel_layouts=mono[a{i}N]"
        )

    # Pairwise xfade + acrossfade.
    filter_parts.append(_build_xfade_chain(len(video_paths), durations, xfade_dur))

    # Final loudnorm pass on the audio chain tail.
    last_audio_label = f"[ax{len(video_paths) - 1}]"
    filter_parts.append(
        f"{last_audio_label}loudnorm=I=-16:TP=-1.5:LRA=11[outa]"
    )

    last_video_label = f"[vx{len(video_paths) - 1}]"

    cmd = [
        "ffmpeg", "-y",
        *input_args,
        "-filter_complex", ";".join(filter_parts),
        "-map", last_video_label,
        "-map", "[outa]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Final concat failed: {result.stderr}")

    return str(output_path)


def _plain_concat(video_paths, video_id, width, height, fps) -> str:
    """Fallback concat (no xfade) when any segment is shorter than the xfade window."""
    output_path = COMBINED_DIR / f"{video_id}_final.mp4"
    input_args = []
    for path in video_paths:
        input_args.extend(["-i", path])
    filter_parts = []
    for i in range(len(video_paths)):
        filter_parts.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={fps},setsar=1,format=yuv420p[v{i}]"
        )
        filter_parts.append(
            f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono[a{i}]"
        )
    stream_pairs = "".join(f"[v{i}][a{i}]" for i in range(len(video_paths)))
    filter_parts.append(
        f"{stream_pairs}concat=n={len(video_paths)}:v=1:a=1[outv][outamix]"
    )
    filter_parts.append("[outamix]loudnorm=I=-16:TP=-1.5:LRA=11[outa]")
    cmd = [
        "ffmpeg", "-y", *input_args,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Plain concat fallback failed: {result.stderr}")
    return str(output_path)


def add_background_music(video_path: str, music_path: str, video_id: str) -> str:
    """Mix background music with video audio using sidechain compression."""
    COMBINED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = COMBINED_DIR / f"{video_id}_final_with_music.mp4"

    duration = get_duration(video_path)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ss", "15",
        "-stream_loop", "-1", "-i", music_path,
        "-filter_complex",
        "[0:a]asplit=2[voice][voicesc];"
        "[1:a]volume=0.3[music_vol];"
        "[music_vol][voicesc]sidechaincompress=ratio=4:threshold=0.02:attack=50:release=500[music_ducked];"
        "[voice][music_ducked]amix=inputs=2:duration=first[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        str(output_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg music mix failed: {result.stderr}")

    return str(output_path)


LOCAL_MUSIC_DIR = Path(os.environ.get('LOCAL_MUSIC_DIR', '/app/music'))


def get_random_background_music(video_id: str) -> Optional[str]:
    """Pick a random music file — from local dir if available, otherwise S3."""
    # Local directory takes priority (dev environment)
    if LOCAL_MUSIC_DIR.is_dir():
        music_files = [
            f for f in LOCAL_MUSIC_DIR.iterdir()
            if f.suffix.lower() in ('.mp3', '.wav')
        ]
        if music_files:
            chosen = random.choice(music_files)
            logger.info(f"[{video_id}] Using local background music: {chosen.name}")
            return str(chosen)
        logger.warning(f"Local music dir {LOCAL_MUSIC_DIR} is empty, trying S3")

    if not MUSIC_BUCKET:
        logger.warning("MUSIC_BUCKET_NAME not set and no local music found, skipping background music")
        return None

    try:
        response = s3.list_objects_v2(Bucket=MUSIC_BUCKET)
        if 'Contents' not in response:
            logger.warning(f"No music found in bucket {MUSIC_BUCKET}")
            return None

        music_files = [
            obj['Key'] for obj in response['Contents']
            if obj['Key'].lower().endswith(('.mp3', '.wav'))
        ]

        if not music_files:
            logger.warning(f"No .mp3 or .wav files in bucket {MUSIC_BUCKET}")
            return None

        selected_key = random.choice(music_files)
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        local_path = AUDIO_DIR / f"bg_music_{video_id}_{Path(selected_key).name}"

        logger.info(f"[{video_id}] Downloading background music: {selected_key}")
        s3.download_file(MUSIC_BUCKET, selected_key, str(local_path))

        return str(local_path)

    except Exception as e:
        logger.error(f"Error fetching background music: {e}")
        return None
