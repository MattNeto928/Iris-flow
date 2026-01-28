// Segment types matching backend - all 14 node types
export type SegmentType = 
  // Original types
  | 'animation' 
  | 'manim' 
  | 'pysim' 
  | 'transition'
  // New node types
  | 'mesa'       // Agent-based modeling
  | 'pymunk'     // 2D physics
  | 'simpy'      // Discrete event simulation
  | 'plotly'     // 3D plots
  | 'networkx'   // Graph algorithms
  | 'audio'      // Sound/signal visualization
  | 'stats'      // Statistical visualizations
  | 'fractal'    // Fractals & cellular automata
  | 'geo'        // Geographic visualization
  | 'chem'       // Molecular structures
  | 'astro';     // Astronomy

export type SegmentStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface VoiceoverConfig {
  text: string;
  voice?: string;
  speed?: number;
}

export interface Segment {
  id: string;
  order: number;
  type: SegmentType;
  title: string;
  description: string;
  voiceover?: VoiceoverConfig;
  metadata: Record<string, unknown>;
  status: SegmentStatus;
  video_path?: string;
  audio_path?: string;
  combined_path?: string;
  duration_seconds?: number;
  logs: string[];
  error?: string;
  generated_script?: string;  // LLM-generated code for pysim/manim
  // UI state
  position?: { x: number; y: number };
}

export interface GenerationJob {
  id: string;
  segments: Segment[];
  current_segment_index: number;
  status: 'idle' | 'running' | 'paused' | 'completed' | 'failed';
  created_at: string;
  updated_at: string;
}

export interface SegmentsResponse {
  segments: Segment[];
  raw_response?: Record<string, unknown>;
}

// API types
export interface PromptRequest {
  prompt: string;
  voice?: string;
  speed?: number;
}

export interface UpdateSegmentsRequest {
  segments: Segment[];
}


export interface SegmentUpdate {
  title?: string;
  description?: string;
  type?: SegmentType;
  voiceover?: VoiceoverConfig;
  metadata?: Record<string, unknown>;
  order?: number;
}
