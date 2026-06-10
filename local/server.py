"""
Local FastAPI server — mirrors the frontend API surface using serverless src/ code.

Endpoints match what the React frontend (api.ts) expects, but all logic
comes from the same codebase that runs in production Batch jobs.
"""

import os
import asyncio
import importlib
import logging
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from local.models import (
    Segment, SegmentStatus, SegmentType, VoiceoverConfig,
    GenerationJob, PromptRequest, SegmentsResponse,
    UpdateSegmentsRequest, SegmentUpdate,
    TestSegmentRequest, SEGMENT_TYPE_DEFAULTS, PreviewPromptRequest,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("local-server")

# ── App ──────────────────────────────────────────────────────

app = FastAPI(title="Iris Flow Local", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Persistent state (JSON file) ─────────────────────────────

OUTPUT_DIR = Path("/app/output")
AUDIO_DIR = OUTPUT_DIR / "audio"
VIDEO_DIR = OUTPUT_DIR / "videos"
COMBINED_DIR = OUTPUT_DIR / "combined"
JOBS_FILE = OUTPUT_DIR / "jobs.json"

for d in [AUDIO_DIR, VIDEO_DIR, COMBINED_DIR]:
    d.mkdir(parents=True, exist_ok=True)

import json as _json


def _save_jobs():
    """Persist all jobs to disk."""
    try:
        data = {jid: job.model_dump(mode="json") for jid, job in jobs.items()}
        JOBS_FILE.write_text(_json.dumps(data, indent=2, default=str))
    except Exception as e:
        logger.error(f"Failed to save jobs: {e}")


def _load_jobs() -> dict[str, GenerationJob]:
    """Load jobs from disk on startup."""
    if not JOBS_FILE.exists():
        return {}
    try:
        data = _json.loads(JOBS_FILE.read_text())
        loaded = {}
        for jid, jdata in data.items():
            loaded[jid] = GenerationJob(**jdata)
        logger.info(f"Loaded {len(loaded)} jobs from disk")
        return loaded
    except Exception as e:
        logger.error(f"Failed to load jobs: {e}")
        return {}


jobs: dict[str, GenerationJob] = _load_jobs()


# ── Service registry (same as serverless worker.py) ──────────

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
    entry = SERVICE_MAP.get(segment_type)
    if not entry:
        raise ValueError(f"Unknown segment type: {segment_type}")
    module_path, class_name = entry
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls()


# ── Segment processing (same logic as worker.py job_visual) ──

async def _process_segment(job: GenerationJob, seg: Segment):
    """Process a single segment — TTS then visual generation."""
    seg.status = SegmentStatus.PROCESSING
    seg.add_log(f"Processing started — type={seg.type}")
    job.updated_at = datetime.utcnow()

    try:
        # 1. TTS
        audio_path = None
        duration = seg.duration_seconds or 8.0

        if seg.voiceover and seg.voiceover.text:
            seg.add_log("Generating TTS audio...")
            from src.services.tts_client import generate_voiceover
            audio_path, duration = await generate_voiceover(
                text=seg.voiceover.text,
                voice=seg.voiceover.voice or "Algenib",
                speed=seg.voiceover.speed or 1.0,
            )
            seg.audio_path = audio_path
            seg.duration_seconds = duration
            seg.add_log(f"TTS complete — {duration:.1f}s")

        if seg.type == "transition":
            import subprocess

            if not audio_path:
                raise RuntimeError("Transition segment must have voiceover audio")

            last_frame_path = None
            for j in range(seg.order - 1, -1, -1):
                prev_seg = job.segments[j]
                if prev_seg.type != 'transition':
                    lf_local = str(OUTPUT_DIR / f"prev_lastframe_local_{job.id[:8]}_{j}.png")
                    if os.path.exists(lf_local):
                        last_frame_path = lf_local
                    break

            if not last_frame_path:
                from PIL import Image
                import numpy as np
                img = Image.fromarray(np.zeros((1920, 1080, 3), dtype=np.uint8))
                last_frame_path = str(OUTPUT_DIR / f"black_frame_{job.id[:8]}_{seg.order}.png")
                img.save(last_frame_path)

            from src.video_utils import compose_transition
            output_path = compose_transition(last_frame_path, audio_path, duration, job.id[:8], seg.order)

            seg.video_path = output_path
            seg.combined_path = output_path
            seg.add_log(f"Transition complete: {output_path}")

        else:
            # 2. Visual generation with retry loop (same as worker.py)
            seg.add_log(f"Generating visual ({seg.type})...")
            description = seg.description

            if seg.type == "mesa":
                description = f"Agent-based simulation using Mesa library: {description}"
            elif seg.type == "pymunk":
                description = f"2D physics simulation using Pymunk library: {description}"

            max_retries = 3
            last_error = None
            video_path = None

            for attempt in range(max_retries):
                try:
                    service = _get_service(seg.type)

                    if seg.type in ("animation", "grok", "remotion"):
                        video_path = await service.generate(
                            description=description,
                            duration=duration,
                            metadata=seg.metadata or {},
                        )
                    else:
                        video_path = await service.generate(
                            description=description,
                            duration=duration,
                            previous_error=last_error if attempt > 0 else None,
                        )

                    if not video_path:
                        raise RuntimeError(f"Visual generation returned None for {seg.type}")

                    # Capture generated code if available
                    if hasattr(service, '_last_script'):
                        seg.generated_script = service._last_script
                        
                    if hasattr(service, '_last_prompt'):
                        seg.llm_prompt = service._last_prompt
                    if hasattr(service, '_last_model'):
                        seg.llm_model = service._last_model

                    break
                except Exception as e:
                    last_error = str(e)
                    if attempt < max_retries - 1:
                        seg.add_log(f"Attempt {attempt + 1} failed: {e}, retrying...")
                    else:
                        raise

            seg.video_path = video_path
            seg.add_log(f"Visual generated: {video_path}")

            # 3. Time-match and combine audio+video (same as worker.py)
            from src.video_utils import match_duration, combine_audio_video

            video_path = match_duration(video_path, duration)

            if audio_path:
                seg.add_log("Combining audio + video...")
                combined_path = combine_audio_video(
                    video_path, audio_path,
                    f"local_{job.id[:8]}", seg.order
                )
                seg.combined_path = combined_path
                seg.add_log(f"Combined: {combined_path}")

            # 4. Extract last frame for transitions
            from src.video_utils import extract_last_frame
            lastframe_path = extract_last_frame(seg.combined_path or seg.video_path, f"local_{job.id[:8]}", seg.order)
            seg.add_log(f"Extracted last frame: {lastframe_path}")

        seg.status = SegmentStatus.COMPLETED
        seg.add_log("Segment complete ✓")

    except Exception as e:
        seg.status = SegmentStatus.FAILED
        seg.error = str(e)
        seg.add_log(f"FAILED: {e}")
        logger.error(f"Segment {seg.id} failed: {e}", exc_info=True)

    job.updated_at = datetime.utcnow()
    _save_jobs()


async def _run_job(job_id: str):
    """Background task: process all pending segments sequentially."""
    job = jobs.get(job_id)
    if not job:
        return

    job.status = "running"
    job.updated_at = datetime.utcnow()

    for i, seg in enumerate(job.segments):
        if job.status == "paused":
            break

        if seg.status in (SegmentStatus.COMPLETED,):
            continue

        job.current_segment_index = i
        await _process_segment(job, seg)

        if seg.status == SegmentStatus.FAILED:
            job.status = "failed"
            job.updated_at = datetime.utcnow()
            _save_jobs()
            return

    # Check if all done
    if all(s.status == SegmentStatus.COMPLETED for s in job.segments):
        # Try concatenation
        try:
            from src.video_utils import concatenate_videos
            video_files = []
            for s in sorted(job.segments, key=lambda x: x.order):
                path = s.combined_path or s.video_path
                if path:
                    video_files.append(path)

            if video_files:
                final_path = concatenate_videos(video_files, job.id[:8])

                # Background music is no longer baked in. Trending audio is
                # attached at publish time by Metricool (TikTok auto-add-music;
                # Instagram via manual-publish workflow).
                job.final_video_path = final_path
                logger.info(f"Final video: {final_path}")
        except Exception as e:
            logger.error(f"Concatenation failed: {e}")

        job.status = "completed"
    elif job.status != "paused":
        job.status = "failed"

    job.updated_at = datetime.utcnow()
    _save_jobs()


# ── API Endpoints ────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "iris-flow-local"}


@app.post("/api/generate-segments", response_model=SegmentsResponse)
async def generate_segments(request: PromptRequest):
    """Generate structured video segments from a prompt using Claude."""
    try:
        from src.services.gemini_client import generate_segments_from_prompt
        raw_segments, master_prompt, master_model = await generate_segments_from_prompt(
            prompt=request.prompt,
            default_voice=request.voice,
            default_speed=request.speed,
        )

        segments = []
        for i, seg in enumerate(raw_segments):
            segments.append(Segment(
                order=i,
                type=seg.type,
                title=seg.title,
                description=seg.description,
                voiceover=VoiceoverConfig(
                    text=seg.voiceover.text,
                    voice=seg.voiceover.voice,
                    speed=seg.voiceover.speed,
                ) if seg.voiceover else None,
                metadata=seg.metadata or {},
            ))

        return SegmentsResponse(
            segments=segments,
            llm_prompt=master_prompt,
            llm_model=master_model
        )
    except Exception as e:
        logger.error(f"Segment generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs", response_model=GenerationJob)
async def create_job(request: UpdateSegmentsRequest):
    """Create a new generation job from segments."""
    job = GenerationJob(
        segments=request.segments, 
        context=request.context,
        llm_prompt=request.llm_prompt,
        llm_model=request.llm_model
    )
    jobs[job.id] = job
    _save_jobs()
    return job


@app.get("/api/jobs/{job_id}", response_model=GenerationJob)
async def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs")
async def list_jobs():
    return {"jobs": list(jobs.values())}


@app.post("/api/jobs/{job_id}/start", response_model=GenerationJob)
async def start_job(job_id: str, background_tasks: BackgroundTasks):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    background_tasks.add_task(asyncio.to_thread, lambda: asyncio.run(_run_job(job_id)))
    return job


@app.post("/api/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = "paused"
    _save_jobs()
    return {"status": "paused"}


@app.put("/api/jobs/{job_id}/segments", response_model=GenerationJob)
async def update_job_segments(job_id: str, request: UpdateSegmentsRequest):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.segments = request.segments
    _save_jobs()
    return job


@app.patch("/api/jobs/{job_id}/segments/{segment_id}")
async def update_segment(job_id: str, segment_id: str, update: SegmentUpdate):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    segment = next((s for s in job.segments if s.id == segment_id), None)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(segment, field, value)
    _save_jobs()
    return segment


@app.delete("/api/jobs/{job_id}/segments/{segment_id}")
async def delete_segment(job_id: str, segment_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.segments = [s for s in job.segments if s.id != segment_id]
    for i, seg in enumerate(job.segments):
        seg.order = i
    _save_jobs()
    return {"deleted": segment_id}


@app.get("/api/jobs/{job_id}/segments/{segment_id}/logs")
async def get_segment_logs(job_id: str, segment_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    segment = next((s for s in job.segments if s.id == segment_id), None)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    return {"segment_id": segment_id, "status": segment.status, "logs": segment.logs, "error": segment.error}


@app.get("/api/jobs/{job_id}/segments/{segment_id}/video")
async def get_segment_video(job_id: str, segment_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    segment = next((s for s in job.segments if s.id == segment_id), None)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    video_path = segment.combined_path or segment.video_path
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(video_path, media_type="video/mp4")


@app.get("/api/jobs/{job_id}/final-video")
async def get_final_video(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.final_video_path or not os.path.exists(job.final_video_path):
        raise HTTPException(status_code=404, detail="Final video not found")
    return FileResponse(
        job.final_video_path,
        media_type="video/mp4",
        filename=f"iris_video_{job.id[:8]}.mp4",
    )


@app.post("/api/jobs/{job_id}/segments/{segment_id}/retry")
async def retry_segment(job_id: str, segment_id: str, background_tasks: BackgroundTasks):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    segment = next((s for s in job.segments if s.id == segment_id), None)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    segment.status = SegmentStatus.PENDING
    segment.error = None
    segment.logs = []

    async def _retry():
        await _process_segment(job, segment)

    background_tasks.add_task(asyncio.to_thread, lambda: asyncio.run(_retry()))

    return {"status": "retrying", "segment_id": segment_id}


@app.post("/api/jobs/{job_id}/resume")
async def resume_job(job_id: str, background_tasks: BackgroundTasks):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    start_index = 0
    for i, seg in enumerate(job.segments):
        if seg.status != SegmentStatus.COMPLETED:
            start_index = i
            break

    job.status = "running"
    background_tasks.add_task(asyncio.to_thread, lambda: asyncio.run(_run_job(job_id)))
    return {"status": "resuming", "from_segment_index": start_index}


# ── TTS Test ─────────────────────────────────────────────────

from pydantic import BaseModel


class TTSTestRequest(BaseModel):
    text: str = "Watch what happens. [pause] The signal just stops."
    voice: str = "xKhbyU7E3bC6T89Kn26c"
    speed: float = 1.0
    stability: float = 0.35
    similarity_boost: float = 0.80
    seed: Optional[int] = None


@app.post("/api/test-tts")
async def test_tts(request: TTSTestRequest):
    try:
        from src.services.tts_client import generate_voiceover
        audio_path, duration = await generate_voiceover(
            text=request.text,
            voice=request.voice,
            speed=request.speed,
            stability=request.stability,
            similarity_boost=request.similarity_boost,
            seed=request.seed,
        )
        return {
            "audio_path": audio_path,
            "duration": duration,
            "audio_url": f"/api/audio/{os.path.basename(audio_path)}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/preview-prompt")
async def preview_prompt(request: PreviewPromptRequest):
    """Return the constructed LLM prompt without executing it."""
    try:
        if request.prompt:
            # It's a master generation prompt request
            from src.services.gemini_client import SEGMENT_GENERATION_PROMPT
            target_duration = request.duration or 90
            full_prompt = SEGMENT_GENERATION_PROMPT + f"\n\nUSER PROMPT: {request.prompt}\nTARGET DURATION: {target_duration} SECONDS"
            return {"prompt": full_prompt}
        elif request.type and request.description:
            # It's a segment tester visual generation prompt
            module = importlib.import_module(f"src.services.{request.type.value}_service")
            prompt_var_name = f"{request.type.value.upper()}_PROMPT"
            prompt_template = getattr(module, prompt_var_name, None)
            
            if not prompt_template:
                return {"prompt": f"[No explicit prompt template configured for {request.type}]"}
            
            duration = request.duration or 8.0
            prompt = prompt_template.replace("{description}", request.description).replace("{duration}", str(duration))
            return {"prompt": prompt}
        else:
            raise HTTPException(status_code=400, detail="Must provide either 'prompt' or 'type' and 'description'")
    except Exception as e:
        logger.error(f"Error generating preview prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/audio/{filename}")
async def get_audio(filename: str):
    audio_path = AUDIO_DIR / filename
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(str(audio_path), media_type="audio/wav")


# ── Segment Tester ───────────────────────────────────────────

@app.get("/api/segment-types")
async def get_segment_types():
    """Return all available segment types with default prompts."""
    return {"types": SEGMENT_TYPE_DEFAULTS}


@app.post("/api/test-segment")
async def test_segment(request: TestSegmentRequest, background_tasks: BackgroundTasks):
    """Create a single-segment job for isolated testing."""
    seg = Segment(
        order=0,
        type=request.type,
        title=f"Test: {SEGMENT_TYPE_DEFAULTS.get(request.type, {}).get('label', request.type)}",
        description=request.description,
        voiceover=request.voiceover,
        duration_seconds=request.duration,
    )

    job = GenerationJob(segments=[seg])
    jobs[job.id] = job
    _save_jobs()

    # Start processing immediately
    background_tasks.add_task(asyncio.to_thread, lambda: asyncio.run(_run_job(job.id)))

    return {"job_id": job.id, "segment_id": seg.id}
