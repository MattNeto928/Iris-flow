import os
import asyncio
import httpx
import math
import subprocess
import uuid
from datetime import datetime
from typing import Dict, Optional, List
from models import Segment, SegmentStatus, SegmentType, GenerationJob
from tts_client import generate_voiceover
from video_combiner import (
    combine_audio_video, 
    match_video_to_audio_duration, 
    add_fade_transition,
    get_media_duration,
    concatenate_videos,
    generate_black_screen_video,
    extract_last_frame,
    create_transition_composition
)
from soundwave_template import SOUNDWAVE_TEMPLATE
from transition_generator import estimate_speech_duration


# Service URLs from environment
ANIM_SERVICE_URL = os.environ.get("ANIM_SERVICE_URL", "http://anim_service:8001")
MANIM_SERVICE_URL = os.environ.get("MANIM_SERVICE_URL", "http://manim_service:8002")
PYSIM_SERVICE_URL = os.environ.get("PYSIM_SERVICE_URL", "http://pysim_service:8003")

# Veo constraints
VEO_MAX_DURATION = 8.0  # Max duration per Veo clip
VEO_MIN_DURATION = 4.0  # Min duration per Veo clip

# In-memory storage for jobs (replace with Redis/DB in production)
jobs: Dict[str, GenerationJob] = {}


async def concatenate_final_video(video_paths: List[str], output_path: str) -> str:
    """
    Concatenate multiple videos into one final video.
    Re-encodes all videos to ensure compatibility (same codec, resolution, etc.)
    Uses FFmpeg concat filter which handles heterogeneous inputs.
    """
    import uuid
    
    # Target specs for all videos (normalize to consistent format)
    target_width = 1280
    target_height = 720
    target_fps = 30
    
    # Build filter complex that scales and normalizes all inputs
    filter_parts = []
    concat_inputs = []
    
    for i in range(len(video_paths)):
        # Scale and pad each video to target resolution, set frame rate
        filter_parts.append(
            f"[{i}:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,fps={target_fps},setsar=1[v{i}]"
        )
        filter_parts.append(f"[{i}:a]aresample=44100[a{i}]")
        concat_inputs.append(f"[v{i}][a{i}]")
    
    # Concatenate all normalized streams
    filter_complex = ";".join(filter_parts)
    concat_str = "".join(concat_inputs)
    filter_complex += f";{concat_str}concat=n={len(video_paths)}:v=1:a=1[outv][outa]"
    
    # Build input arguments
    input_args = []
    for path in video_paths:
        input_args.extend(["-i", path])
    
    cmd = [
        "ffmpeg", "-y",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]
    
    print(f"[FinalConcat] Concatenating {len(video_paths)} videos...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"[FinalConcat] FFmpeg stderr: {result.stderr}")
        raise RuntimeError(f"Final concat failed: {result.stderr}")
    
    print(f"[FinalConcat] Success: {output_path}")
    return output_path


async def process_segment(
    segment: Segment, 
    job: GenerationJob,
    prev_segment: Optional[Segment] = None,
    job_context: str = ""
) -> Segment:
    """
    Process a single segment through the video generation pipeline.
    
    Enhanced pipeline:
    1. Generate transition narration (if not first segment)
    2. Generate main voiceover, prepend transition, get total duration
    3. Generate visual(s) to match audio duration
    4. Time-stretch video if needed
    5. Combine audio + video
    """
    segment.status = SegmentStatus.PROCESSING
    segment.add_log("Starting segment processing")
    
    try:
        # Step 1: Generate audio
        audio_path = None
        duration = 5.0  # Default duration
        
        if segment.voiceover:
            segment.add_log(f"Generating voiceover with voice: {segment.voiceover.voice}")
            audio_path, duration = await generate_voiceover(
                text=segment.voiceover.text,
                voice=segment.voiceover.voice,
                speed=segment.voiceover.speed
            )
            segment.add_log(f"Voiceover generated: {duration:.2f}s")
            
        segment.audio_path = audio_path
        segment.duration_seconds = duration

        # Step 2: Generate visual based on type
        segment.add_log(f"Generating {segment.type.value} visual ({duration:.2f}s)")
        
        video_path = None
        
        if segment.type == SegmentType.TRANSITION:
            # Enhanced Transition: Audio Wave + Last Frame Fade
            segment.add_log("Generating sound wave transition...")
            
            # 1. Extract Last Frame from previous segment (if available)
            last_frame_path = None
            if prev_segment and (prev_segment.combined_path or prev_segment.video_path):
                prev_video = prev_segment.combined_path or prev_segment.video_path
                try:
                    last_frame_path = extract_last_frame(prev_video)
                    segment.add_log(f"Extracted last frame: {last_frame_path}")
                except Exception as e:
                    segment.add_log(f"Warning: Failed to extract last frame: {e}")
            
            # If no last frame, use a black image (can be generated or just handled by transition composer if None)
            # Actually, composer handles it if we pass a black image path or we can generate one here.
            # Let's generate a fallback black image if needed.
            if not last_frame_path:
                # Use black screen generator to make a 1 frame video or just use a placeholder 
                # Better: Ensure extract_last_frame handles it? No.
                # Let's just default to a black image.
                # For now let's skip image generation and let composer fallback if logical, 
                # but composer expects an image path.
                # Hack: Generate a 0.1s black video and extract frame? Or just use a static black image asset.
                pass 

            # 2. Generate Manim Sound Wave Script
            # We need the absolute path to the audio file for the Manim script to read it
            # Docker volumes: 'shared_videos' is mounted at /videos
            # The audio path is likely /videos/audio/something.wav
            
            # Populate tempalte
            manim_script = SOUNDWAVE_TEMPLATE.format(audio_path=audio_path)
            
            # 3. Call Manim Service with explicit script
            # We reuse generate_visual but need to pass the script
            # Our generate_visual function uses the generic /generate endpoint.
            # We need to modify generate_visual or just call the service manually here?
            # Let's modify generate_visual to accept 'script' in metadata or argument.
            
            # Let's invoke generic generate, passing script in metadata or a new field?
            # The model and service expect 'description'. 
            # I modified Manim service to look for 'script' in request body.
            # So I need to pass 'script' in the API call.
            
            segment.metadata['script'] = manim_script
            # We need to tell generate_visual to include this in the payload.
            # Modify generate_visual below or here.
            
            # Call generate_visual (which calls manim service)
            # Note: manim service will return a video of the sound wave (black bg)
            # We call it 'overlay_video'
            overlay_video, _ = await generate_visual(segment, duration, script=manim_script)
            segment.add_log(f"Generated sound wave overlay: {overlay_video}")
            
            # 4. Compose Final Transition
            # If no last frame, we need a fallback.
            # create_transition_composition expects a background image.
            # If None, it fails.
            if not last_frame_path:
                 # Create a temp black image
                 import numpy as np
                 from PIL import Image
                 img = Image.fromarray(np.zeros((720, 1280, 3), dtype=np.uint8))
                 last_frame_path = f"/videos/black_frame_{uuid.uuid4().hex}.png"
                 img.save(last_frame_path)
            
            video_path = await create_transition_composition(
                background_image=last_frame_path,
                overlay_video=overlay_video,
                audio_path=audio_path
            )
            segment.add_log(f"Composed final transition: {video_path}")
            
        elif segment.type == SegmentType.ANIMATION:
            # Multi-clip Veo generation for long segments
            video_path = await generate_veo_clips(segment, duration)
            
        else:
            # Single-shot for Manim/PySim
            # 1. Generate script first (so it's visible in UI immediately)
            try:
                segment.add_log("Generating script...")
                generated_script = await generate_script_preview(segment, duration)
                segment.generated_script = generated_script
                segment.add_log("Script generated ready for view")
                # Force update to ensure frontend sees it
                # (Ideally we'd trigger a specialized update here, but add_log does trigger updated_at)
            except Exception as e:
                # If script gen fails, we can't proceed
                segment.add_log(f"Script generation failed: {e}")
                raise

            # 2. Run simulation with the generated script
            segment.add_log("Running simulation...")
            video_path, _ = await generate_visual(segment, duration, script=generated_script)
        
        if not video_path:
            raise RuntimeError("Visual generation failed (script captured for debugging)")
            
        segment.video_path = video_path
        segment.add_log(f"Visual generated: {video_path}")
        
        # Step 3: Time-stretch video to match audio exactly (if not transition)
        # For transitions, we generated exact duration, so no need to stretch
        if segment.type != SegmentType.TRANSITION:
            video_duration = get_media_duration(video_path)
            if audio_path and abs(video_duration - duration) > 0.5:
                segment.add_log(f"Time-stretching video: {video_duration:.2f}s -> {duration:.2f}s")
                video_path = await match_video_to_audio_duration(
                    video_path, 
                    duration
                )
                segment.add_log("Video time-stretched")
            
        # Step 4: Combine audio + video
        if audio_path and video_path:
            segment.add_log("Combining audio and video")
            combined_path = await combine_audio_video(video_path, audio_path)
            segment.combined_path = combined_path
            segment.add_log(f"Combined video: {combined_path}")
        else:
            segment.combined_path = video_path
            
        segment.status = SegmentStatus.COMPLETED
        segment.add_log("Segment completed successfully")
        
    except Exception as e:
        segment.status = SegmentStatus.FAILED
        segment.error = str(e)
        segment.add_log(f"ERROR: {str(e)}")
        raise
    
    return segment


async def generate_veo_clips(segment: Segment, target_duration: float) -> str:
    """
    Generate one or more Veo clips to cover the target duration.
    
    Veo only generates 4, 6, or 8 second clips. For longer content,
    we generate multiple clips with varied perspectives and crossfade them.
    """
    # Calculate number of clips needed
    num_clips = max(1, math.ceil(target_duration / VEO_MAX_DURATION))
    clip_duration = min(VEO_MAX_DURATION, max(VEO_MIN_DURATION, target_duration / num_clips))
    
    segment.add_log(f"Generating {num_clips} Veo clip(s), ~{clip_duration:.1f}s each")
    
    if num_clips == 1:
        # Simple single clip (Veo doesn't generate scripts)
        video_path, _ = await generate_visual(segment, clip_duration)
        return video_path
    
    # Generate multiple clips with varied perspectives
    perspective_prompts = [
        "",  # Original
        "Show this from a different angle. ",
        "Zoom in on a key detail. ",
        "Pull back to show the broader context. ",
        "Focus on the most visually interesting element. ",
    ]
    
    clip_paths: List[str] = []
    
    for i in range(num_clips):
        perspective = perspective_prompts[i % len(perspective_prompts)]
        varied_description = f"{perspective}{segment.description}"
        
        segment.add_log(f"Generating clip {i+1}/{num_clips}")
        
        # Create a modified segment for this clip
        clip_segment = Segment(
            order=segment.order,
            type=segment.type,
            title=f"{segment.title} (clip {i+1})",
            description=varied_description,
            metadata=segment.metadata
        )
        
        clip_path, _ = await generate_visual(clip_segment, clip_duration)
        clip_paths.append(clip_path)
    
    # Crossfade all clips together
    if len(clip_paths) == 1:
        return clip_paths[0]
    
    segment.add_log(f"Crossfading {len(clip_paths)} clips")
    
    # Chain crossfades: 1+2, then result+3, etc.
    result_path = clip_paths[0]
    for i, next_clip in enumerate(clip_paths[1:], 1):
        segment.add_log(f"Crossfading clips {i}/{len(clip_paths)-1}")
        result_path = await add_fade_transition(result_path, next_clip, fade_duration=0.5)
    
    return result_path


async def generate_visual(segment: Segment, duration: float, script: str = None) -> tuple[str, str | None]:
    """
    Call the appropriate service to generate the visual component.
    Returns (video_path, generated_script) tuple.
    """
    service_url = get_service_url(segment.type)
    
    payload = {
        "description": segment.description,
        "title": segment.title,
        "duration_seconds": duration,
        "metadata": segment.metadata
    }
    
    if script:
        payload["script"] = script
    
    async with httpx.AsyncClient(timeout=600.0) as client:  # 10 min timeout
        response = await client.post(
            f"{service_url}/generate",
            json=payload
        )
        
        if response.status_code != 200:
            # Check if we have a script in the error response (from pysim service)
            if response.status_code == 422:
                try:
                    error_data = response.json()
                    if "script" in error_data:
                        # We have the script but execution failed.
                        # Return None for video_path but return the script
                        # The caller should handle the missing video path by raising an error
                        # AFTER saving the script
                        return None, error_data["script"]
                except Exception:
                    pass
                    
            raise RuntimeError(f"Service returned {response.status_code}: {response.text}")
        
        result = response.json()
        # Return both video path and generated script (if available)
        return result.get("video_path"), result.get("script")


async def generate_script_preview(segment: Segment, duration: float) -> str:
    """
    Generate the simulation script without running it.
    """
    service_url = get_service_url(segment.type)
    
    payload = {
        "description": segment.description,
        "title": segment.title,
        "duration_seconds": duration,
        "metadata": segment.metadata
    }
    
    async with httpx.AsyncClient(timeout=120.0) as client:  # 2 min timeout for script gen
        response = await client.post(
            f"{service_url}/preview-script",
            json=payload
        )
        
        if response.status_code != 200:
            raise RuntimeError(f"Script generation failed {response.status_code}: {response.text}")
        
        return response.json().get("script")


def get_service_url(segment_type: SegmentType) -> str:
    """Get the appropriate service URL for a segment type."""
    if segment_type == SegmentType.ANIMATION:
        return ANIM_SERVICE_URL
    elif segment_type == SegmentType.MANIM:
        return MANIM_SERVICE_URL
    elif segment_type == SegmentType.PYSIM:
        return PYSIM_SERVICE_URL
    elif segment_type == SegmentType.TRANSITION:
        return MANIM_SERVICE_URL
    else:
        raise ValueError(f"Unknown segment type: {segment_type}")


async def concatenate_audio_files(audio1_path: str, audio2_path: str) -> str:
    """Concatenate two audio files using FFmpeg."""
    import subprocess
    import uuid
    
    output_dir = "/videos/audio"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"concat_{uuid.uuid4().hex}.wav")
    
    # Create concat list file
    list_path = f"/tmp/audio_concat_{uuid.uuid4().hex}.txt"
    with open(list_path, "w") as f:
        f.write(f"file '{audio1_path}'\n")
        f.write(f"file '{audio2_path}'\n")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.remove(list_path)
    
    if result.returncode != 0:
        raise RuntimeError(f"Audio concat failed: {result.stderr}")
    
    return output_path


async def run_generation_job(job: GenerationJob) -> GenerationJob:
    """
    Run a full video generation job, processing segments sequentially.
    Includes transition generation between segments.
    Pauses on failure to allow user intervention.
    """
    job.status = "running"
    job.updated_at = datetime.utcnow()
    
    print(f"[JOB] Starting job {job.id} with {len(job.segments)} segments")
    
    prev_segment = None
    
    for i, segment in enumerate(job.segments):
        if job.status == "paused":
            break
            
        job.current_segment_index = i
        
        print(f"[JOB] Processing segment {i}: {segment.type.value} - {segment.title}")
        
        try:
            await process_segment(segment, job, prev_segment=prev_segment, job_context=job.context or "")
            prev_segment = segment
        except Exception as e:
            # Pause on failure and LOG THE ERROR
            print(f"[JOB ERROR] Segment {i} failed: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            job.status = "paused"
            job.updated_at = datetime.utcnow()
            break
    
    # Check if all completed
    all_completed = all(
        s.status == SegmentStatus.COMPLETED 
        for s in job.segments
    )
    
    if all_completed:
        # Concatenate all segment videos into final video
        try:
            print(f"[Job] All segments completed, concatenating final video...")
            segment_videos = [
                s.combined_path or s.video_path 
                for s in sorted(job.segments, key=lambda x: x.order)
                if (s.combined_path or s.video_path)
            ]
            
            if segment_videos:
                final_output = f"/videos/combined/final_{job.id}.mp4"
                
                if len(segment_videos) == 1:
                    # Just copy if only one segment
                    import shutil
                    shutil.copy(segment_videos[0], final_output)
                else:
                    # Use simple concatenation with re-encoding for compatibility
                    # This handles videos with different codecs/resolutions
                    await concatenate_final_video(segment_videos, final_output)
                
                job.final_video_path = final_output
                print(f"[Job] Final video: {final_output}")
            
        except Exception as e:
            import traceback
            print(f"[Job] ERROR concatenating final video: {e}")
            print(f"[Job] Traceback: {traceback.format_exc()}")
            # Don't fail the job, just log the error
        
        job.status = "completed"
    
    job.updated_at = datetime.utcnow()
    return job


def create_job(segments: list[Segment], context: Optional[str] = None) -> GenerationJob:
    """Create a new generation job."""
    job = GenerationJob(segments=segments, context=context)
    jobs[job.id] = job
    return job


def get_job(job_id: str) -> Optional[GenerationJob]:
    """Get a job by ID."""
    return jobs.get(job_id)


async def start_job(job_id: str) -> GenerationJob:
    """Start or resume a job."""
    job = jobs.get(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    
    # Start processing in background
    asyncio.create_task(run_generation_job(job))
    
    return job


async def retry_segment(job_id: str, segment_id: str) -> Segment:
    """
    Retry a failed segment without affecting the overall job flow.
    
    This allows the user to retry just the failed block. After a successful
    retry, the job can be resumed from where it left off.
    
    Returns immediately with the segment in PROCESSING state while
    the actual processing continues in the background.
    """
    job = jobs.get(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    
    # Find the segment
    segment = next((s for s in job.segments if s.id == segment_id), None)
    if not segment:
        raise ValueError(f"Segment not found: {segment_id}")
    
    # Reset segment state - set to PROCESSING immediately so frontend sees it
    segment.status = SegmentStatus.PROCESSING
    segment.error = None
    segment.video_path = None
    segment.audio_path = None
    segment.combined_path = None
    segment.logs = []
    segment.add_log("Retry initiated - starting segment processing")
    
    # Find previous segment for context (needed for transitions)
    segment_index = next(i for i, s in enumerate(job.segments) if s.id == segment_id)
    prev_segment = job.segments[segment_index - 1] if segment_index > 0 else None
    
    # Process in background (non-blocking)
    print(f"[Retry] Starting background retry for segment {segment_id} ({segment.title})")
    asyncio.create_task(_process_segment_retry(segment, job, prev_segment))
    
    return segment


async def _process_segment_retry(segment: Segment, job: GenerationJob, prev_segment: Optional[Segment]):
    """Internal: Process a segment retry in the background."""
    try:
        await process_segment(segment, job, prev_segment, job.context or "")
        print(f"[Retry] Segment {segment.id} completed successfully")
    except Exception as e:
        print(f"[Retry] Segment {segment.id} failed: {e}")
        import traceback
        traceback.print_exc()
        # segment.status is already set to FAILED by process_segment


async def resume_job_from_segment(job_id: str, segment_index: int) -> GenerationJob:
    """
    Resume a job starting from a specific segment index.
    Useful after a successful retry to continue processing remaining segments.
    """
    job = jobs.get(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    
    job.status = "running"
    job.updated_at = datetime.utcnow()
    job.current_segment_index = segment_index
    
    # Start processing from the given index
    asyncio.create_task(_run_job_from_index(job, segment_index))
    
    return job


async def _run_job_from_index(job: GenerationJob, start_index: int):
    """Internal: Run job starting from a specific segment index."""
    prev_segment = job.segments[start_index - 1] if start_index > 0 else None
    
    for i in range(start_index, len(job.segments)):
        if job.status == "paused":
            break
            
        segment = job.segments[i]
        job.current_segment_index = i
        
        # Skip already completed segments
        if segment.status == SegmentStatus.COMPLETED:
            prev_segment = segment
            continue
        
        print(f"[JOB] Processing segment {i}: {segment.type.value} - {segment.title}")
        
        try:
            await process_segment(segment, job, prev_segment=prev_segment, job_context=job.context or "")
            prev_segment = segment
        except Exception as e:
            print(f"[JOB ERROR] Segment {i} failed: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            job.status = "paused"
            job.updated_at = datetime.utcnow()
            return
    
    # Check if all completed
    all_completed = all(s.status == SegmentStatus.COMPLETED for s in job.segments)
    
    if all_completed:
        try:
            print(f"[Job] All segments completed, concatenating final video...")
            segment_videos = [
                s.combined_path or s.video_path 
                for s in sorted(job.segments, key=lambda x: x.order)
                if (s.combined_path or s.video_path)
            ]
            
            if segment_videos:
                final_output = f"/videos/combined/final_{job.id}.mp4"
                
                if len(segment_videos) == 1:
                    import shutil
                    shutil.copy(segment_videos[0], final_output)
                else:
                    await concatenate_final_video(segment_videos, final_output)
                
                job.final_video_path = final_output
                print(f"[Job] Final video: {final_output}")
                
        except Exception as e:
            import traceback
            print(f"[Job] ERROR concatenating final video: {e}")
            print(f"[Job] Traceback: {traceback.format_exc()}")
        
        job.status = "completed"
    
    job.updated_at = datetime.utcnow()
