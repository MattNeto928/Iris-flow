"""
Pydantic models for the local FastAPI server.
Adapted from main_service/app/models.py to work with the serverless codebase.
"""

from pydantic import BaseModel
from typing import Optional, List, Literal
from enum import Enum
import uuid
from datetime import datetime


class SegmentType(str, Enum):
    ANIMATION = "animation"
    MANIM = "manim"
    PYSIM = "pysim"
    TRANSITION = "transition"
    MESA = "mesa"
    PYMUNK = "pymunk"
    SIMPY = "simpy"
    PLOTLY = "plotly"
    NETWORKX = "networkx"
    AUDIO = "audio"
    STATS = "stats"
    FRACTAL = "fractal"
    GEO = "geo"
    CHEM = "chem"
    ASTRO = "astro"
    GROK = "grok"
    REMOTION = "remotion"


class SegmentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VoiceoverConfig(BaseModel):
    text: str
    voice: str = "xKhbyU7E3bC6T89Kn26c"
    speed: float = 1.0


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
    logs: List[str] = []
    error: Optional[str] = None
    generated_script: Optional[str] = None
    llm_prompt: Optional[str] = None
    llm_model: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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
    voice: str = "Algenib"
    speed: float = 1.0


class SegmentsResponse(BaseModel):
    segments: List[Segment]
    raw_response: Optional[dict] = None
    llm_prompt: Optional[str] = None
    llm_model: Optional[str] = None


class GenerationJob(BaseModel):
    id: str = ""
    segments: List[Segment]
    current_segment_index: int = 0
    status: Literal["idle", "running", "paused", "completed", "failed"] = "idle"
    final_video_path: Optional[str] = None
    context: Optional[str] = None
    llm_prompt: Optional[str] = None
    llm_model: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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
    llm_prompt: Optional[str] = None
    llm_model: Optional[str] = None


class SegmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[SegmentType] = None
    voiceover: Optional[VoiceoverConfig] = None
    metadata: Optional[dict] = None
    order: Optional[int] = None


class TestSegmentRequest(BaseModel):
    type: SegmentType
    description: str
    voiceover: Optional[VoiceoverConfig] = None
    duration: float = 8.0


class PreviewPromptRequest(BaseModel):
    type: Optional[SegmentType] = None
    description: Optional[str] = None
    prompt: Optional[str] = None
    duration: Optional[float] = None


# Default prompts for each segment type — used by the Segment Tester
SEGMENT_TYPE_DEFAULTS = {
    "pysim": {
        "label": "PySim (Scientific Simulation)",
        "description": "Simulate a chaotic double pendulum with trails and energy conservation plot",
        "icon": "🔬",
    },
    "manim": {
        "label": "Manim (Math Visualization)",
        "description": "Animate the derivation of Euler's identity, showing e^(iπ) + 1 = 0 on the complex plane",
        "icon": "📐",
    },
    "animation": {
        "label": "Animation (Veo 3.1)",
        "description": "A cinematic flythrough of a bioluminescent deep-sea cave with glowing jellyfish",
        "icon": "🎬",
    },
    "mesa": {
        "label": "Mesa (Agent-Based Modeling)",
        "description": "Agent-based simulation of predator-prey dynamics with population visualization",
        "icon": "🐺",
    },
    "pymunk": {
        "label": "Pymunk (2D Physics)",
        "description": "Simulate a Newton's cradle with 5 pendulum balls showing momentum transfer",
        "icon": "⚡",
    },
    "simpy": {
        "label": "SimPy (Discrete Event Sim)",
        "description": "Simulate a multi-server queueing system showing wait times and throughput",
        "icon": "🏭",
    },
    "plotly": {
        "label": "Plotly (3D Visualization)",
        "description": "Rotating 3D surface plot of the Rosenbrock function with gradient descent path",
        "icon": "📊",
    },
    "networkx": {
        "label": "NetworkX (Graph Algorithms)",
        "description": "Visualize Dijkstra's shortest path algorithm on a weighted graph with animation",
        "icon": "🕸️",
    },
    "audio": {
        "label": "Audio (Sound Visualization)",
        "description": "Visualize a harmonic series with individual frequencies combining into a complex waveform",
        "icon": "🎵",
    },
    "stats": {
        "label": "Stats (Statistical Viz)",
        "description": "Animate the Central Limit Theorem: rolling dice samples converging to a normal distribution",
        "icon": "📈",
    },
    "fractal": {
        "label": "Fractal (Fractals & Automata)",
        "description": "Zoom into the Mandelbrot set boundary, revealing self-similar structures",
        "icon": "🌀",
    },
    "geo": {
        "label": "Geo (Geographic Viz)",
        "description": "Animate the spread of the Internet across the globe from 1990 to 2024",
        "icon": "🌍",
    },
    "chem": {
        "label": "Chem (Molecular Structures)",
        "description": "Visualize the structure and rotation of a caffeine molecule with labeled atoms",
        "icon": "⚗️",
    },
    "astro": {
        "label": "Astro (Astronomy)",
        "description": "Simulate the inner solar system showing orbital mechanics and Kepler's laws",
        "icon": "🔭",
    },
    "grok": {
        "label": "Grok (AI Generation)",
        "description": "Generate a photorealistic visualization of a supernova explosion",
        "icon": "🤖",
    },
    "remotion": {
        "label": "Remotion (React Video)",
        "description": "Use ThreeCanvas to render a rotating DNA double helix made of glowing spheres in electric blue and gold. The helix should slowly rotate on the Y axis driven by useCurrentFrame(), with a subtle point light casting colored shadows. Overlay a title 'The Blueprint of Life' in large white text that fades in at the bottom third of the frame.",
        "icon": "⚛️",
    },
    "transition": {
        "label": "Transition",
        "description": "A smooth narrative transition bridging two topics",
        "icon": "🔗",
    },
}
