import os
import subprocess
import uuid


VIDEO_OUTPUT_DIR = "/videos/combined"


def generate_black_screen_video(duration: float, output_path: str = None) -> str:
    """
    Generate a black screen video of a specific duration.
    """
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
    
    if not output_path:
        output_path = os.path.join(VIDEO_OUTPUT_DIR, f"black_{uuid.uuid4().hex}.mp4")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s=1280x720:r=30:d={duration}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        output_path
    ]
    
    print(f"[BlackScreen] Generating {duration}s black screen")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg black screen generation failed: {result.stderr}")
    
    return output_path


def get_media_duration(file_path: str) -> float:
    """Get the duration of a media file in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def has_audio_stream(file_path: str) -> bool:
    """Check if a media file has an audio stream using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0 and "audio" in result.stdout.strip().lower()


async def match_video_to_audio_duration(
    video_path: str,
    target_duration: float,
    output_path: str = None
) -> str:
    """
    Time-stretch a video to match a target duration using FFmpeg.
    
    Uses setpts filter to adjust video speed and atempo for audio (if present).
    Works reliably for speed factors between 0.5x and 2.0x.
    For larger mismatches, chains multiple operations.
    
    Args:
        video_path: Path to the input video
        target_duration: Desired duration in seconds
        output_path: Optional output path
        
    Returns:
        Path to the time-stretched video
    """
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
    
    if not output_path:
        output_path = os.path.join(VIDEO_OUTPUT_DIR, f"stretched_{uuid.uuid4().hex}.mp4")
    
    video_duration = get_media_duration(video_path)
    
    if abs(video_duration - target_duration) < 0.1:
        # Close enough, just copy
        import shutil
        shutil.copy(video_path, output_path)
        return output_path
    
    # Calculate speed factor (< 1 = slower, > 1 = faster)
    speed_factor = video_duration / target_duration
    
    print(f"[VideoMatch] Video: {video_duration:.2f}s, Target: {target_duration:.2f}s, Speed factor: {speed_factor:.3f}")
    
    # PTS factor is inverse of speed (slower = higher PTS multiplier)
    pts_factor = 1 / speed_factor
    
    # Build filter chain
    # For video: setpts adjusts timestamps
    video_filter = f"setpts={pts_factor}*PTS"
    
    # Check if source has audio before building audio filters
    source_has_audio = has_audio_stream(video_path)
    print(f"[VideoMatch] Source has audio: {source_has_audio}")
    
    audio_filter = None
    if source_has_audio:
        # For audio: atempo adjusts speed (limited to 0.5-2.0 per filter)
        # Chain atempo filters for extreme speed changes
        audio_filters = []
        remaining_speed = speed_factor
        while remaining_speed > 2.0:
            audio_filters.append("atempo=2.0")
            remaining_speed /= 2.0
        while remaining_speed < 0.5:
            audio_filters.append("atempo=0.5")
            remaining_speed /= 0.5
        if remaining_speed != 1.0:
            audio_filters.append(f"atempo={remaining_speed:.4f}")
        
        audio_filter = ",".join(audio_filters) if audio_filters else None
    
    # Build FFmpeg command
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-filter:v", video_filter,
    ]
    
    if audio_filter:
        cmd.extend(["-filter:a", audio_filter])
        cmd.extend([
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            output_path
        ])
    else:
        # No audio track - don't include any audio codec options
        cmd.extend([
            "-an",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "23",
            output_path
        ])
    
    print(f"[VideoMatch] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg time-stretch failed: {result.stderr}")
    
    actual_duration = get_media_duration(output_path)
    print(f"[VideoMatch] Result duration: {actual_duration:.2f}s (target: {target_duration:.2f}s)")
    
    return output_path


async def add_fade_transition(
    video1_path: str,
    video2_path: str,
    fade_duration: float = 0.5,
    output_path: str = None
) -> str:
    """
    Concatenate two videos with a crossfade transition.
    
    Args:
        video1_path: Path to first video
        video2_path: Path to second video
        fade_duration: Duration of crossfade in seconds
        output_path: Optional output path
        
    Returns:
        Path to the combined video with fade transition
    """
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
    
    if not output_path:
        output_path = os.path.join(VIDEO_OUTPUT_DIR, f"faded_{uuid.uuid4().hex}.mp4")
    
    # Get durations to calculate offset
    dur1 = get_media_duration(video1_path)
    
    # xfade offset is when the transition starts (end of first clip minus fade duration)
    offset = dur1 - fade_duration
    
    # Build xfade filter for video and acrossfade for audio
    filter_complex = (
        f"[0:v][1:v]xfade=transition=fade:duration={fade_duration}:offset={offset}[v];"
        f"[0:a][1:a]acrossfade=d={fade_duration}[a]"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video1_path,
        "-i", video2_path,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        output_path
    ]
    
    print(f"[FadeTransition] Combining with {fade_duration}s crossfade")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        # Fallback: try without audio crossfade (in case one video has no audio)
        filter_complex = f"[0:v][1:v]xfade=transition=fade:duration={fade_duration}:offset={offset}[v]"
        cmd = [
            "ffmpeg", "-y",
            "-i", video1_path,
            "-i", video2_path,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "23",
            "-an",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg xfade failed: {result.stderr}")
    
    return output_path





async def combine_audio_video(
    video_path: str,
    audio_path: str,
    output_filename: str = None
) -> str:
    """
    Combine an audio file with a video file using FFmpeg.
    
    If the audio is longer than the video, the video will be extended by
    freezing the last frame until the audio finishes.
    
    Args:
        video_path: Path to the video file
        audio_path: Path to the audio file
        output_filename: Optional filename for the output
        
    Returns:
        Path to the combined video file
    """
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
    
    if not output_filename:
        output_filename = f"combined_{uuid.uuid4().hex}.mp4"
    
    output_path = os.path.join(VIDEO_OUTPUT_DIR, output_filename)
    
    # Get durations of both files
    video_duration = get_media_duration(video_path)
    audio_duration = get_media_duration(audio_path)
    
    print(f"[Combine] Video: {video_duration:.2f}s, Audio: {audio_duration:.2f}s")
    
    if audio_duration > video_duration + 0.5:
        # Audio is significantly longer - extend video by freezing last frame
        extra_duration = audio_duration - video_duration
        print(f"[Combine] Extending video by {extra_duration:.2f}s (freeze last frame)")
        
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", f"[0:v]tpad=stop_mode=clone:stop_duration={extra_duration}[v]",
            "-map", "[v]",
            "-map", "1:a",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path
        ]
    else:
        # Video is longer or equal - simple mux (re-encode for compatibility)
        print(f"[Combine] Simple mux with re-encode")
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path
        ]
    
    print(f"[Combine] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"[Combine] FFmpeg error: {result.stderr}")
        raise RuntimeError(f"FFmpeg combine failed: {result.stderr}")
    
    print(f"[Combine] Success: {output_path}")
    return output_path


async def add_audio_to_video(
    video_path: str,
    audio_path: str,
    output_path: str
) -> str:
    """
    Add audio to a video, replacing any existing audio track.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr}")
    
    return output_path


async def concatenate_videos(video_paths: list[str], output_path: str) -> str:
    """
    Concatenate multiple video files into one.
    """
    # Create a temporary file listing all videos
    list_file = "/tmp/video_list.txt"
    with open(list_file, "w") as f:
        for path in video_paths:
            f.write(f"file '{path}'\n")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg concat failed: {result.stderr}")
    
    return output_path


def extract_last_frame(video_path: str, output_path: str = None) -> str:
    """
    Extract the last frame of a video as an image (simulating a freeze frame).
    Uses the video duration to seek to the very end.
    """
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
    if not output_path:
        output_path = os.path.join(VIDEO_OUTPUT_DIR, f"last_frame_{uuid.uuid4().hex}.png")

    duration = get_media_duration(video_path)
    # Seek slightly before the end to ensure we get a valid frame
    # If video is very short, seek to 0
    seek_time = max(0.0, duration - 0.1)
    if duration < 0.2:
        seek_time = 0.0
    
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(seek_time),
        "-i", video_path,
        "-frames:v", "1",
        output_path
    ]
    
    # Debug info
    print(f"[ExtractFrame] Extracting from {video_path} at {seek_time}s (dur: {duration}s)")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg frame extraction failed: {result.stderr}")
    
    # Verify file was actually created
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        # Try fallback: seek to beginning
        print(f"[ExtractFrame] Warning: No frame at end, trying beginning...")
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-frames:v", "1",
            output_path
        ]
        subprocess.run(cmd, capture_output=True, text=True)
        
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
             raise RuntimeError(f"Could not extract frame from video: {video_path} (ffmpeg stderr: {result.stderr})")
        
    return output_path


async def create_transition_composition(
    background_image: str,
    overlay_video: str,
    audio_path: str,
    output_path: str = None
) -> str:
    """
    Compose the transition video:
    1. Background image (darkened) 
    2. Overlay video (sound wave) on top using addition blend
    3. Transition Audio
    
    Resolution: 1920x1080 @ 30fps
    """
    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
    if not output_path:
        output_path = os.path.join(VIDEO_OUTPUT_DIR, f"transition_comp_{uuid.uuid4().hex}.mp4")
        
    # Get audio duration to determine video length
    duration = get_media_duration(audio_path)
    
    # Resolution and framerate
    width = 1920
    height = 1080
    fps = 30
    
    # Filter explanation:
    # 1. Create black background at target resolution
    # 2. Take the last frame image, scale to target, darken it (eq=brightness filter)
    # 3. Overlay the darkened image onto black
    # 4. Take the soundwave video (black bg), use 'addition' blend to add only the bright parts
    #    Addition blend: output = min(255, bg + overlay) - effectively makes black transparent
    
    # Using eq=brightness=-0.6 to darken the image (range -1 to 1, negative = darker)
    # Then blend with 'addition' mode for the soundwave
    
    # Fade timing
    fade_in_dur = 0.5   # Quick background darkening
    wave_fade_in = 0.4  # Wave fades in
    fade_out_dur = 0.5  # Fade out at end
    fade_out_start = max(0, duration - fade_out_dur)  # Start fade out before end
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r={fps}:d={duration}",  # 0: Black BG
        "-loop", "1", "-t", str(duration), "-i", background_image,                       # 1: Image (looped)
        "-i", overlay_video,                                                              # 2: Soundwave
        "-i", audio_path,                                                                 # 3: Audio
        "-filter_complex",
        # Step 1: Prepare image with RGBA, animated alpha fade
        # Alpha: starts at 255, fades to 76 (30%) over fade_in_dur, then at end fades to 0
        f"[1:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},setsar=1,"
        f"format=rgba,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
        f"a='if(lt(T,{fade_in_dur}),255*(1-0.7*T/{fade_in_dur}),"  # Fade in phase: 255 -> 76
        f"if(gt(T,{fade_out_start}),255*0.3*(1-(T-{fade_out_start})/{fade_out_dur}),"  # Fade out phase: 76 -> 0
        f"255*0.3))'[faded_img];"  # Hold phase: stay at 76
        # Step 2: Overlay faded image on black
        f"[0:v][faded_img]overlay=shortest=1[bg];"
        # Step 3: Prepare soundwave with fade-in and fade-out
        # Since blend=lighten ignores alpha, we fade by modifying RGB values directly
        # Multiply R,G,B by opacity factor
        f"[2:v]scale={width}:{height},fps={fps},setsar=1,"
        # Opacity factor: 0->1 over wave_fade_in, 1 in middle, 1->0 over fade_out
        # geq with r,g,b multiplied by opacity expression
        f"geq="
        f"r='r(X,Y)*if(lt(T,{wave_fade_in}),T/{wave_fade_in},if(gt(T,{fade_out_start}),(1-(T-{fade_out_start})/{fade_out_dur}),1))':"
        f"g='g(X,Y)*if(lt(T,{wave_fade_in}),T/{wave_fade_in},if(gt(T,{fade_out_start}),(1-(T-{fade_out_start})/{fade_out_dur}),1))':"
        f"b='b(X,Y)*if(lt(T,{wave_fade_in}),T/{wave_fade_in},if(gt(T,{fade_out_start}),(1-(T-{fade_out_start})/{fade_out_dur}),1))'[wave];"
        # Step 4: Convert both to gbrp for color-accurate blending  
        f"[bg]format=gbrp[bg_gbrp];"
        f"[wave]format=gbrp[wave_gbrp];"
        # Step 5: Lighten blend to overlay soundwave
        f"[bg_gbrp][wave_gbrp]blend=all_mode=lighten:shortest=1[blended];"
        f"[blended]format=yuv420p[outv]",
        "-map", "[outv]",
        "-map", "3:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        output_path
    ]
    
    print(f"[TransitionComp] Running composition at {width}x{height}@{fps}fps...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"[TransitionComp] FFmpeg stderr: {result.stderr}")
        raise RuntimeError(f"FFmpeg composition failed: {result.stderr}")
        
    return output_path
