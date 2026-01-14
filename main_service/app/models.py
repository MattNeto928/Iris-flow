from pydantic import BaseModel
from typing import Optional, List, Literal
from enum import Enum
import uuid
from datetime import datetime


class SegmentType(str, Enum):
    ANIMATION = "animation"  # Gemini Veo 3.1
    MANIM = "manim"          # Claude + Manim
    PYSIM = "pysim"          # Claude + Python Simulation
    TRANSITION = "transition" # Black screen + voiceover


class SegmentStatus(str, Enum):
    PENDING = "pending"      # Grey - not started
    PROCESSING = "processing" # Yellow - in progress
    COMPLETED = "completed"   # Green - done
    FAILED = "failed"        # Red - error


class VoiceoverConfig(BaseModel):
    text: str
    voice: str = "Schedar"  # Default Gemini TTS voice
    speed: float = 1.35


class Segment(BaseModel):
    id: str = ""
    order: int
    type: SegmentType
    title: str
    description: str
    voiceover: Optional[VoiceoverConfig] = None
    metadata: dict = {}
    status: SegmentStatus = SegmentStatus.PENDING
    video_path: Optional[str] = None
    audio_path: Optional[str] = None
    combined_path: Optional[str] = None
    duration_seconds: Optional[float] = None
    # Transition fields - for bridging from previous segment
    transition_text: Optional[str] = None  # Generated transition narration
    transition_audio_path: Optional[str] = None  # Path to transition audio
    logs: List[str] = []
    error: Optional[str] = None
    generated_script: Optional[str] = None  # For pysim/manim: the LLM-generated code
    created_at: datetime = None
    updated_at: datetime = None

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def add_log(self, message: str):
        timestamp = datetime.utcnow().isoformat()
        self.logs.append(f"[{timestamp}] {message}")
        self.updated_at = datetime.utcnow()


class PromptRequest(BaseModel):
    prompt: str
    voice: str = "Schedar"
    speed: float = 1.35


class SegmentsResponse(BaseModel):
    segments: List[Segment]
    raw_response: Optional[dict] = None


class GenerationJob(BaseModel):
    id: str = ""
    segments: List[Segment]
    current_segment_index: int = 0
    status: Literal["idle", "running", "paused", "completed", "failed"] = "idle"
    final_video_path: Optional[str] = None  # Path to concatenated final video
    context: Optional[str] = None  # Setup context/prompt for the whole generation
    created_at: datetime = None
    updated_at: datetime = None

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()


class UpdateSegmentsRequest(BaseModel):
    segments: List[Segment]
    context: Optional[str] = None


class SegmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[SegmentType] = None
    voiceover: Optional[VoiceoverConfig] = None
    metadata: Optional[dict] = None
    order: Optional[int] = None
