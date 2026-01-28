"""
Video Pipeline - Full video generation from prompt to final video.

Adapted from local Iris-flow state machine for serverless execution.
Processes segments sequentially: TTS -> Visual -> Combine -> Concatenate.
"""

import os
import uuid
import logging
import asyncio
import subprocess
import random
from pathlib import Path
from datetime import datetime
from typing import Optional
import boto3

from src.services.gemini_client import generate_segments_from_prompt, generate_caption
from src.services.tts_client import generate_voiceover
from src.services.pysim_service import PysimService
from src.services.veo_service import VeoService
from src.services.manim_service import ManimService
# New node type services
from src.services.simpy_service import SimpyService
from src.services.plotly_service import PlotlyService
from src.services.networkx_service import NetworkxService
from src.services.audio_service import AudioService
from src.services.stats_service import StatsService
from src.services.fractal_service import FractalService
from src.services.geo_service import GeoService
from src.services.chem_service import ChemService
from src.services.astro_service import AstroService

logger = logging.getLogger(__name__)

# S3 client
s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
VIDEO_BUCKET = os.environ.get('VIDEO_BUCKET_NAME')
MUSIC_BUCKET = os.environ.get('MUSIC_BUCKET_NAME')

# Local working directories
OUTPUT_DIR = Path("/app/output")
AUDIO_DIR = OUTPUT_DIR / "audio"
VIDEO_DIR = OUTPUT_DIR / "videos"
COMBINED_DIR = OUTPUT_DIR / "combined"


class VideoPipeline:
    def __init__(self):
        # Core services
        self.pysim = PysimService()
        self.veo = VeoService()
        self.manim = ManimService()
        
        # New node type services
        self.simpy = SimpyService()
        self.plotly = PlotlyService()
        self.networkx = NetworkxService()
        self.audio = AudioService()
        self.stats = StatsService()
        self.fractal = FractalService()
        self.geo = GeoService()
        self.chem = ChemService()
        self.astro = AstroService()
        
        # Ensure directories exist
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        COMBINED_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate_video(
        self,
        prompt: str,
        topic_id: str,
        category: str
    ) -> dict:
        """
        Generate a complete video from a topic prompt.
        
        Pipeline:
        1. Generate segments from prompt (Gemini)
        2. Process each segment (TTS + visual generation)
        3. Concatenate all segments
        4. Upload to S3
        5. Generate caption
        
        Returns:
            dict with keys: success, video_url, caption, youtube_title, error
        """
        video_id = f"{topic_id}_{str(uuid.uuid4())[:4]}"
        
        try:
            # Step 1: Generate segments from prompt
            logger.info(f"[{video_id}] Generating segments from prompt...")
            segments = await generate_segments_from_prompt(
                prompt=prompt,
                default_voice="Fenrir",  # Veritasium-style voice
                default_speed=1.15
            )
            logger.info(f"[{video_id}] Generated {len(segments)} segments")
            
            # Log the entire segment flow
            flow_str = " -> ".join([seg.type for seg in segments])
            logger.info(f"[{video_id}] Segment Flow: {flow_str}")
            
            # Step 2: Process each segment
            segment_videos = []
            prev_segment = None
            
            for i, segment in enumerate(segments):
                logger.info(f"[{video_id}] Processing segment {i+1}/{len(segments)}: {segment.type} - {segment.title}")
                
                try:
                    combined_path = await self._process_segment_with_retry(
                        segment=segment,
                        video_id=video_id,
                        segment_index=i,
                        prev_segment=prev_segment,
                        context=prompt,
                        max_retries=3
                    )
                    
                    if combined_path:
                        segment_videos.append(combined_path)
                        prev_segment = segment
                        logger.info(f"[{video_id}] Segment {i+1} completed: {combined_path}")
                    
                except Exception as e:
                    logger.error(f"[{video_id}] Segment {i+1} failed after all retries: {e}")
                    # Continue with other segments
                    continue
            
            if not segment_videos:
                raise Exception("No segments were successfully processed")
            
            # Step 3: Concatenate all segments
            logger.info(f"[{video_id}] Concatenating {len(segment_videos)} segments...")
            final_path = await self._concatenate_videos(segment_videos, video_id)
            
            # Step 3.5: Add background music
            logger.info(f"[{video_id}] Check background music...")
            try:
                music_path = await self._get_random_background_music(video_id)
                if music_path:
                    logger.info(f"[{video_id}] Adding background music layer...")
                    final_path_with_music = await self._add_background_music(final_path, music_path, video_id)
                    final_path = final_path_with_music
                    logger.info(f"[{video_id}] Background music added: {final_path}")
            except Exception as e:
                logger.error(f"[{video_id}] Failed to add background music (proceeding without): {e}")
            
            # Step 4: Upload to S3
            logger.info(f"[{video_id}] Uploading to S3...")
            s3_key = f"videos/{datetime.now().strftime('%Y/%m/%d')}/{video_id}.mp4"
            
            s3.upload_file(
                str(final_path),
                VIDEO_BUCKET,
                s3_key,
                ExtraArgs={'ContentType': 'video/mp4'}
            )
            
            # Generate public URL
            video_url = f"https://{VIDEO_BUCKET}.s3.amazonaws.com/{s3_key}"
            logger.info(f"[{video_id}] Uploaded: {video_url}")
            
            # Step 5: Generate caption and title
            logger.info(f"[{video_id}] Generating caption...")
            caption = await generate_caption(prompt)
            youtube_title = prompt[:97] + '...' if len(prompt) > 100 else prompt
            
            return {
                'success': True,
                'video_id': video_id,
                'video_url': video_url,
                'caption': caption,
                'youtube_title': youtube_title
            }
            
        except Exception as e:
            logger.error(f"[{video_id}] Pipeline failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'video_id': video_id,
                'error': str(e)
            }
    
    async def _process_segment_with_retry(
        self,
        segment,
        video_id: str,
        segment_index: int,
        prev_segment=None,
        context: str = "",
        max_retries: int = 3
    ) -> Optional[str]:
        """
        Process a segment with retry logic.
        
        If the segment fails (especially PySim/Manim script errors), retry with
        the error message included in the prompt to help Claude fix it.
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Pass any previous error to the processor
                return await self._process_segment(
                    segment=segment,
                    video_id=video_id,
                    segment_index=segment_index,
                    prev_segment=prev_segment,
                    context=context,
                    previous_error=last_error if attempt > 0 else None
                )
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    logger.warning(f"[{video_id}] Segment {segment_index + 1} attempt {attempt + 1} failed: {e}")
                    logger.info(f"[{video_id}] Retrying segment {segment_index + 1} (attempt {attempt + 2}/{max_retries})...")
                else:
                    raise  # Re-raise on final attempt
        
        return None  # Should not reach here
    
    async def _process_segment(
        self,
        segment,
        video_id: str,
        segment_index: int,
        prev_segment=None,
        context: str = "",
        previous_error: Optional[str] = None
    ) -> Optional[str]:
        """Process a single segment: TTS -> Visual -> Combine."""
        
        # Step 1: Generate audio (TTS)
        audio_path = None
        duration = 5.0
        
        if segment.voiceover:
            logger.info(f"[{video_id}] Generating voiceover...")
            audio_path, duration = await generate_voiceover(
                text=segment.voiceover.text,
                voice=segment.voiceover.voice,
                speed=segment.voiceover.speed
            )
            logger.info(f"[{video_id}] Voiceover: {duration:.2f}s")
        
        # Step 2: Generate visual based on type
        logger.info(f"[{video_id}] Generating {segment.type} visual ({duration:.2f}s)...")
        
        video_path = None
        
        if segment.type == "transition":
            # Transition handling - matches local state_machine.py logic
            # Transitions MUST have audio (no silent fallback)
            if not audio_path:
                raise RuntimeError("Transition segment must have voiceover audio")
            
            logger.info(f"[{video_id}] Generating soundwave transition...")
            
            # 1. Extract last frame from previous segment (if available)
            last_frame_path = None
            if prev_segment:
                prev_video = getattr(prev_segment, 'combined_path', None) or getattr(prev_segment, 'video_path', None)
                if prev_video:
                    try:
                        last_frame_path = await self._extract_last_frame(prev_video, video_id, segment_index)
                        logger.info(f"[{video_id}] Extracted last frame: {last_frame_path}")
                    except Exception as e:
                        logger.warning(f"[{video_id}] Failed to extract last frame: {e}")
            
            # 2. Generate black frame if no last frame available
            if not last_frame_path:
                from PIL import Image
                import numpy as np
                img = Image.fromarray(np.zeros((1920, 1080, 3), dtype=np.uint8))
                last_frame_path = str(OUTPUT_DIR / f"black_frame_{video_id}_{segment_index}.png")
                img.save(last_frame_path)
            
            # 3. Generate soundwave overlay using Manim
            from src.soundwave_template import SOUNDWAVE_TEMPLATE
            manim_script = SOUNDWAVE_TEMPLATE.format(audio_path=audio_path)
            overlay_video = await self.manim.generate_from_script(
                script=manim_script,
                duration=duration
            )
            logger.info(f"[{video_id}] Generated soundwave overlay: {overlay_video}")
            
            # 4. Compose final transition: darkened background + soundwave overlay + audio
            # Using sophisticated composition from local implementation:
            # - Animated alpha fade on background (100% → 30% → 0%)
            # - Soundwave fade in/out
            # - gbrp format for color-accurate blending
            output_path = VIDEO_DIR / f"{video_id}_seg{segment_index}_transition.mp4"
            
            # Fade timing (matches local video_combiner.py)
            fade_in_dur = 0.5   # Background dims from 100% → 30%
            wave_fade_in = 0.4  # Wave appears gradually
            fade_out_dur = 0.5  # Everything fades to black
            fade_out_start = max(0, duration - fade_out_dur)
            
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:r=30:d={duration}",  # 0: Black BG
                "-loop", "1", "-t", str(duration), "-i", last_frame_path,  # 1: Background image
                "-i", overlay_video,  # 2: Soundwave video
                "-i", audio_path,  # 3: Audio
                "-filter_complex",
                # ---------------------------------------------------------
                # OPTIMIZED FADE GENERATION
                # Instead of calculating expressions for 2 million pixels per frame,
                # we calculate them on a 1x1 pixel video and scale it up.
                # ---------------------------------------------------------
                
                # 1. Generate Background Alpha Curve (1x1 pixel)
                # Matches: 100% -> 30% (over fade_in_dur) -> hold -> 0% (at fade_out_start)
                f"color=c=black:s=1x1:d={duration}[bg_curve_base];"
                f"[bg_curve_base]geq=lum='if(lt(T,{fade_in_dur}),255*(1-0.7*T/{fade_in_dur}),"
                f"if(gt(T,{fade_out_start}),255*0.3*(1-(T-{fade_out_start})/{fade_out_dur}),"
                f"255*0.3))':a=255[bg_curve_1x1];"
                f"[bg_curve_1x1]scale=1080:1920:flags=neighbor[bg_alpha_mask];"

                # 2. Generate Wave Intensity Curve (1x1 pixel)
                # Matches: 0% -> 100% (over wave_fade_in) -> hold -> 0% (at fade_out_start)
                f"color=c=black:s=1x1:d={duration}[wave_curve_base];"
                f"[wave_curve_base]geq=lum='255*if(lt(T,{wave_fade_in}),T/{wave_fade_in},"
                f"if(gt(T,{fade_out_start}),(1-(T-{fade_out_start})/{fade_out_dur}),1))':a=255[wave_curve_1x1];"
                f"[wave_curve_1x1]scale=1080:1920:flags=neighbor[wave_intensity_mask];"

                # 3. Process Background Image
                # Apply alpha mask to image
                f"[1:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
                f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1,format=rgba[bg_img];"
                f"[bg_img][bg_alpha_mask]alphamerge[bg_faded];"

                # 4. Process Wave Video
                # Multiply wave by intensity mask (fades white to black)
                # We use gbrp format + blend=multiply. 
                # Since wave is black/white, multiplying by intensity dims the white parts.
                f"[2:v]scale=1080:1920,fps=30,setsar=1,format=gbrp[wave_base];"
                f"[wave_intensity_mask]format=gbrp[wave_mask_gbrp];"
                f"[wave_base][wave_mask_gbrp]blend=all_mode=multiply[wave_faded];"

                # 5. Composite
                # Overlay faded bg on black
                f"[0:v][bg_faded]overlay=shortest=1[comp_bg];"
                # Add wave using lighten (or add) since it's white-on-black
                f"[comp_bg]format=gbrp[comp_bg_gbrp];"
                f"[comp_bg_gbrp][wave_faded]blend=all_mode=lighten:shortest=1[final_video_gbrp];"
                f"[final_video_gbrp]format=yuv420p[outv]",
                "-map", "[outv]",
                "-map", "3:a",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k",
                "-t", str(duration),
                str(output_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Transition composition failed: {result.stderr}")
            
            video_path = str(output_path)
            logger.info(f"[{video_id}] Soundwave transition created: {video_path}")
            
            # Mark as already combined (has audio)
            segment.combined_path = video_path
            segment.video_path = video_path
            return video_path
            
        elif segment.type == "pysim":
            # PySim: Claude-generated Python simulation
            video_path = await self.pysim.generate(
                description=segment.description,
                duration=duration,
                previous_error=previous_error
            )
            
        elif segment.type == "animation":
            # Animation: Veo 3.1 video generation (disabled by prompt, but keep for compatibility)
            video_path = await self.veo.generate(
                description=segment.description,
                duration=duration,
                metadata=segment.metadata
            )
            
        elif segment.type == "manim":
            # Manim: Claude-generated Manim scene
            video_path = await self.manim.generate(
                description=segment.description,
                duration=duration,
                previous_error=previous_error
            )
        
        # === NEW NODE TYPES ===
        
        elif segment.type == "mesa":
            # Mesa: Agent-based modeling (flocking, epidemics, economics)
            # Uses pysim since mesa outputs to matplotlib
            video_path = await self.pysim.generate(
                description=f"Agent-based simulation using Mesa library: {segment.description}",
                duration=duration,
                previous_error=previous_error
            )
        
        elif segment.type == "pymunk":
            # Pymunk: 2D physics simulation
            # Uses pysim since pymunk outputs to matplotlib
            video_path = await self.pysim.generate(
                description=f"2D physics simulation using Pymunk library: {segment.description}",
                duration=duration,
                previous_error=previous_error
            )
        
        elif segment.type == "simpy":
            # SimPy: Discrete event simulation
            video_path = await self.simpy.generate(
                description=segment.description,
                duration=duration,
                previous_error=previous_error
            )
        
        elif segment.type == "plotly":
            # Plotly: 3D plots and complex visualizations
            video_path = await self.plotly.generate(
                description=segment.description,
                duration=duration,
                previous_error=previous_error
            )
        
        elif segment.type == "networkx":
            # NetworkX: Graph algorithms and networks
            video_path = await self.networkx.generate(
                description=segment.description,
                duration=duration,
                previous_error=previous_error
            )
        
        elif segment.type == "audio":
            # Audio: Sound and signal visualization
            video_path = await self.audio.generate(
                description=segment.description,
                duration=duration,
                previous_error=previous_error
            )
        
        elif segment.type == "stats":
            # Stats: Statistical visualizations
            video_path = await self.stats.generate(
                description=segment.description,
                duration=duration,
                previous_error=previous_error
            )
        
        elif segment.type == "fractal":
            # Fractal: Mandelbrot, Julia, Game of Life
            video_path = await self.fractal.generate(
                description=segment.description,
                duration=duration,
                previous_error=previous_error
            )
        
        elif segment.type == "geo":
            # Geo: Map projections and geographic data
            video_path = await self.geo.generate(
                description=segment.description,
                duration=duration,
                previous_error=previous_error
            )
        
        elif segment.type == "chem":
            # Chem: Molecular structures
            video_path = await self.chem.generate(
                description=segment.description,
                duration=duration,
                previous_error=previous_error
            )
        
        elif segment.type == "astro":
            # Astro: Astronomy and celestial mechanics
            video_path = await self.astro.generate(
                description=segment.description,
                duration=duration,
                previous_error=previous_error
            )
        
        if not video_path:
            raise RuntimeError(f"Visual generation failed for {segment.type}")
        
        # Store paths on segment for next iteration
        segment.video_path = video_path
        
        # Step 3: Match video duration to audio (skip for transitions - already exact)
        if segment.type != "transition":
            video_path = await self._match_duration(video_path, duration)
        
        # Step 4: Combine audio and video
        if audio_path:
            combined_path = await self._combine_audio_video(
                video_path, audio_path, video_id, segment_index
            )
            segment.combined_path = combined_path
            return combined_path
        else:
            segment.combined_path = video_path
            return video_path
    
    async def _generate_soundwave_transition(
        self,
        audio_path: str,
        duration: float,
        prev_segment,
        video_id: str,
        segment_index: int
    ) -> str:
        """Generate a fancy transition with soundwave overlay on darkened last frame."""
        from src.soundwave_template import SOUNDWAVE_TEMPLATE
        
        logger.info(f"[{video_id}] Generating soundwave transition...")
        
        # 1. Extract last frame from previous segment
        prev_video = getattr(prev_segment, 'combined_path', None) or getattr(prev_segment, 'video_path', None)
        last_frame_path = None
        
        if prev_video:
            try:
                last_frame_path = await self._extract_last_frame(prev_video, video_id, segment_index)
                logger.info(f"[{video_id}] Extracted last frame: {last_frame_path}")
            except Exception as e:
                logger.warning(f"[{video_id}] Failed to extract last frame: {e}")
        
        # 2. Generate black frame if no last frame available
        if not last_frame_path:
            from PIL import Image
            import numpy as np
            img = Image.fromarray(np.zeros((1920, 1080, 3), dtype=np.uint8))
            last_frame_path = str(OUTPUT_DIR / f"black_frame_{video_id}_{segment_index}.png")
            img.save(last_frame_path)
        
        # 3. Generate soundwave overlay using Manim
        manim_script = SOUNDWAVE_TEMPLATE.format(audio_path=audio_path)
        overlay_video = await self.manim.generate_from_script(
            script=manim_script,
            duration=duration
        )
        
        # 4. Composite: darkened last frame + soundwave overlay
        output_path = VIDEO_DIR / f"{video_id}_seg{segment_index}_transition.mp4"
        
        # Use FFmpeg to:
        # - Darken the background image
        # - Overlay the soundwave video using 'lighten' blend
        # - Add the audio
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-t", str(duration), "-i", last_frame_path,  # 0: Background image
            "-i", overlay_video,  # 1: Soundwave video
            "-i", audio_path,  # 2: Audio
            "-filter_complex",
            "[0:v]scale=1080:1920,format=rgb24,eq=brightness=-0.4[bg];"
            "[1:v]scale=1080:1920,format=rgb24[wave];"
            "[bg][wave]blend=all_mode=lighten:shortest=1,format=yuv420p[outv]",
            "-map", "[outv]",
            "-map", "2:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(duration),
            str(output_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Transition composition failed: {result.stderr}")
        
        logger.info(f"[{video_id}] Soundwave transition created: {output_path}")
        return str(output_path)
    
    async def _extract_last_frame(self, video_path: str, video_id: str, segment_index: int) -> str:
        """Extract the last frame from a video."""
        output_path = OUTPUT_DIR / f"last_frame_{video_id}_{segment_index}.png"
        
        # Get video duration
        duration = self._get_duration(video_path)
        seek_time = max(0, duration - 0.1)
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(seek_time),
            "-i", video_path,
            "-frames:v", "1",
            str(output_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not output_path.exists():
            raise RuntimeError(f"Frame extraction failed: {result.stderr}")
        
        return str(output_path)
    
    async def _generate_black_screen(
        self,
        duration: float,
        video_id: str,
        segment_index: int
    ) -> str:
        """Generate a black screen video."""
        # 9:16 vertical format for Shorts/Reels/TikTok
        output_path = VIDEO_DIR / f"{video_id}_seg{segment_index}_black.mp4"
        
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s=1080x1920:r=30:d={duration}",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "23",
            str(output_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg black screen failed: {result.stderr}")
        
        return str(output_path)
    
    async def _match_duration(self, video_path: str, target_duration: float) -> str:
        """Time-stretch video to match target duration."""
        video_duration = self._get_duration(video_path)
        
        if abs(video_duration - target_duration) < 0.5:
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
    
    async def _combine_audio_video(
        self,
        video_path: str,
        audio_path: str,
        video_id: str,
        segment_index: int
    ) -> str:
        """Combine audio and video into final segment."""
        output_path = COMBINED_DIR / f"{video_id}_seg{segment_index}_combined.mp4"
        
        video_duration = self._get_duration(video_path)
        audio_duration = self._get_duration(audio_path)
        
        if audio_duration > video_duration + 0.5:
            # Extend video by freezing last frame
            extra = audio_duration - video_duration
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-filter_complex", f"[0:v]tpad=stop_mode=clone:stop_duration={extra}[v]",
                "-map", "[v]",
                "-map", "1:a",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k",
                str(output_path)
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(output_path)
            ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Audio/video combine failed: {result.stderr}")
        
        return str(output_path)
    
    async def _concatenate_videos(self, video_paths: list[str], video_id: str) -> str:
        """Concatenate multiple videos into final output."""
        output_path = COMBINED_DIR / f"{video_id}_final.mp4"
        
        if len(video_paths) == 1:
            import shutil
            shutil.copy(video_paths[0], output_path)
            return str(output_path)
        
        # 9:16 vertical format
        width, height = 1080, 1920
        fps = 30
        
        # Build filter complex
        filter_parts = []
        concat_inputs = []
        
        for i in range(len(video_paths)):
            filter_parts.append(
                f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},setsar=1[v{i}]"
            )
            filter_parts.append(f"[{i}:a]aresample=44100[a{i}]")
            concat_inputs.append(f"[v{i}][a{i}]")
        
        filter_complex = ";".join(filter_parts)
        concat_str = "".join(concat_inputs)
        filter_complex += f";{concat_str}concat=n={len(video_paths)}:v=1:a=1[outv][outa]"
        
        input_args = []
        for path in video_paths:
            input_args.extend(["-i", path])
        
        cmd = [
            "ffmpeg", "-y",
            *input_args,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Final concat failed: {result.stderr}")
        
        return str(output_path)
    
    def _get_duration(self, path: str) -> float:
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

    async def _get_random_background_music(self, video_id: str) -> Optional[str]:
        """Fetch a random music file from S3."""
        if not MUSIC_BUCKET:
            logger.warning("MUSIC_BUCKET_NAME not set, skipping background music")
            return None
            
        try:
            # List objects
            response = s3.list_objects_v2(Bucket=MUSIC_BUCKET)
            if 'Contents' not in response:
                logger.warning(f"No music found in bucket {MUSIC_BUCKET}")
                return None
                
            # Filter for audio files
            music_files = [
                obj['Key'] for obj in response['Contents'] 
                if obj['Key'].lower().endswith(('.mp3', '.wav'))
            ]
            
            if not music_files:
                logger.warning(f"No .mp3 or .wav files in bucket {MUSIC_BUCKET}")
                return None
                
            # Pick accessible random file
            selected_key = random.choice(music_files)
            local_path = AUDIO_DIR / f"bg_music_{video_id}_{Path(selected_key).name}"
            
            logger.info(f"[{video_id}] Downloading background music: {selected_key}")
            s3.download_file(MUSIC_BUCKET, selected_key, str(local_path))
            
            return str(local_path)
            
        except Exception as e:
            logger.error(f"Error fetching background music: {e}")
            return None

    async def _add_background_music(self, video_path: str, music_path: str, video_id: str) -> str:
        """Mix background music with video audio."""
        output_path = COMBINED_DIR / f"{video_id}_final_with_music.mp4"
        
        # Calculate duration to trim music
        duration = self._get_duration(video_path)
        
        # FFmpeg command to:
        # 1. Loop music input (stream 1)
        # 2. Mix original audio (stream 0) at 100% volume
        # 3. Mix music audio (stream 1) at 10% volume
        # 4. Trim to video duration
        
        # Note: amix duration=first ensures the output is as long as the first input (video audio)
        # We also enforce -t just in case
        
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", "15",  # Start 15 seconds into the song
            "-stream_loop", "-1", "-i", music_path,
            "-filter_complex", 
            "[0:a]volume=1.0[original];[1:a]volume=0.2[music];[original][music]amix=inputs=2:duration=first[a]",
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
