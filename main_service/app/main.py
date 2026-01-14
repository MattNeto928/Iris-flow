from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import List, Optional
from pydantic import BaseModel
import os

from models import (
    PromptRequest, SegmentsResponse, Segment, 
    GenerationJob, UpdateSegmentsRequest, SegmentUpdate
)
from gemini_client import generate_segments_from_prompt
from state_machine import create_job, get_job, start_job, jobs
from tts_client import generate_voiceover


app = FastAPI(
    title="Iris Main Service",
    description="Video generation orchestrator",
    version="1.0.0"
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "main_service"}


@app.post("/api/generate-segments", response_model=SegmentsResponse)
async def generate_segments(request: PromptRequest):
    """
    Take a user prompt and generate a structured list of video segments.
    """
    try:
        segments = await generate_segments_from_prompt(
            request.prompt,
            default_voice=request.voice,
            default_speed=request.speed
        )
        return SegmentsResponse(segments=segments)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs", response_model=GenerationJob)
async def create_generation_job(request: UpdateSegmentsRequest):
    """
    Create a new generation job with the provided segments.
    """
    job = create_job(request.segments, context=request.context)
    return job


@app.get("/api/jobs/{job_id}", response_model=GenerationJob)
async def get_generation_job(job_id: str):
    """
    Get the status of a generation job.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs/{job_id}/start", response_model=GenerationJob)
async def start_generation_job(job_id: str):
    """
    Start or resume a generation job.
    """
    try:
        job = await start_job(job_id)
        return job
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/jobs/{job_id}/pause")
async def pause_generation_job(job_id: str):
    """
    Pause a running generation job.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = "paused"
    return {"status": "paused"}


@app.put("/api/jobs/{job_id}/segments", response_model=GenerationJob)
async def update_job_segments(job_id: str, request: UpdateSegmentsRequest):
    """
    Update the segments in a job (for reordering, editing, etc.).
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job.segments = request.segments
    return job


@app.patch("/api/jobs/{job_id}/segments/{segment_id}")
async def update_segment(job_id: str, segment_id: str, update: SegmentUpdate):
    """
    Update a specific segment in a job.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    segment = next((s for s in job.segments if s.id == segment_id), None)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    
    # Apply updates
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(segment, field, value)
    
    return segment


@app.delete("/api/jobs/{job_id}/segments/{segment_id}")
async def delete_segment(job_id: str, segment_id: str):
    """
    Delete a segment from a job.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job.segments = [s for s in job.segments if s.id != segment_id]
    
    # Reorder remaining segments
    for i, segment in enumerate(job.segments):
        segment.order = i
    
    return {"deleted": segment_id}


@app.post("/api/jobs/{job_id}/segments/{segment_id}/retry")
async def retry_segment_endpoint(job_id: str, segment_id: str):
    """
    Retry a failed segment without affecting the overall job flow.
    After retry, use /resume to continue processing remaining segments.
    """
    from state_machine import retry_segment
    try:
        segment = await retry_segment(job_id, segment_id)
        return {
            "status": "ok" if segment.status.value == "completed" else "failed",
            "segment_id": segment.id,
            "segment_status": segment.status.value,
            "error": segment.error
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/jobs/{job_id}/resume")
async def resume_job_endpoint(job_id: str):
    """
    Resume a paused job, continuing from where it left off.
    Useful after retrying a failed segment.
    """
    from state_machine import resume_job_from_segment
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Find the first non-completed segment
    start_index = 0
    for i, seg in enumerate(job.segments):
        if seg.status.value != "completed":
            start_index = i
            break
    
    job = await resume_job_from_segment(job_id, start_index)
    return {"status": "resuming", "from_segment_index": start_index}


@app.get("/api/jobs/{job_id}/segments/{segment_id}/logs")
async def get_segment_logs(job_id: str, segment_id: str):
    """
    Get the processing logs for a specific segment.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    segment = next((s for s in job.segments if s.id == segment_id), None)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    
    return {
        "segment_id": segment_id,
        "status": segment.status,
        "logs": segment.logs,
        "error": segment.error
    }


@app.get("/api/jobs/{job_id}/segments/{segment_id}/video")
async def get_segment_video(job_id: str, segment_id: str):
    """
    Serve the generated video for a completed segment.
    """
    job = get_job(job_id)
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
    """
    Serve the final concatenated video for a completed job.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != "completed":
        raise HTTPException(status_code=400, detail=f"Job not completed (status: {job.status})")
    
    if not job.final_video_path or not os.path.exists(job.final_video_path):
        raise HTTPException(status_code=404, detail="Final video not found")
    
    return FileResponse(
        job.final_video_path, 
        media_type="video/mp4",
        filename=f"iris_video_{job_id[:8]}.mp4"
    )


@app.get("/api/jobs")
async def list_jobs():
    """
    List all jobs.
    """
    return {"jobs": list(jobs.values())}


class TTSTestRequest(BaseModel):
    text: str = "Hello! This is a test of the Gemini text to speech system."
    voice: str = "Schedar"
    speed: float = 1.0


@app.post("/api/test-tts")
async def test_tts(request: TTSTestRequest):
    """
    Test TTS generation and return the audio file.
    """
    try:
        audio_path, duration = await generate_voiceover(
            text=request.text,
            voice=request.voice,
            speed=request.speed
        )
        return {
            "audio_path": audio_path,
            "duration": duration,
            "audio_url": f"/api/audio/{os.path.basename(audio_path)}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/audio/{filename}")
async def get_audio(filename: str):
    """
    Serve audio files for testing.
    """
    audio_path = f"/videos/audio/{filename}"
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(audio_path, media_type="audio/wav")
