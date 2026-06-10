import type { Segment, SegmentsResponse, GenerationJob, UpdateSegmentsRequest } from '../types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

class ApiService {
  private baseUrl: string;

  constructor() {
    this.baseUrl = API_URL;
  }

  async generateSegments(prompt: string, voice?: string, speed?: number): Promise<SegmentsResponse> {
    const response = await fetch(`${this.baseUrl}/api/generate-segments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, voice, speed }),
    });
    
    if (!response.ok) {
      throw new Error(`Failed to generate segments: ${response.statusText}`);
    }
    
    return response.json();
  }

  async createJob(segments: Segment[]): Promise<GenerationJob> {
    const response = await fetch(`${this.baseUrl}/api/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ segments }),
    });
    
    if (!response.ok) {
      throw new Error(`Failed to create job: ${response.statusText}`);
    }
    
    return response.json();
  }

  async getJob(jobId: string): Promise<GenerationJob> {
    const response = await fetch(`${this.baseUrl}/api/jobs/${jobId}`);
    
    if (!response.ok) {
      throw new Error(`Failed to get job: ${response.statusText}`);
    }
    
    return response.json();
  }

  async listJobs(): Promise<{ jobs: GenerationJob[] }> {
    const response = await fetch(`${this.baseUrl}/api/jobs`);
    if (!response.ok) {
      throw new Error(`Failed to list jobs: ${response.statusText}`);
    }
    return response.json();
  }

  async startJob(jobId: string): Promise<GenerationJob> {
    const response = await fetch(`${this.baseUrl}/api/jobs/${jobId}/start`, {
      method: 'POST',
    });
    
    if (!response.ok) {
      throw new Error(`Failed to start job: ${response.statusText}`);
    }
    
    return response.json();
  }

  async pauseJob(jobId: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/jobs/${jobId}/pause`, {
      method: 'POST',
    });
    
    if (!response.ok) {
      throw new Error(`Failed to pause job: ${response.statusText}`);
    }
  }

  async updateJobSegments(jobId: string, segments: Segment[]): Promise<GenerationJob> {
    const response = await fetch(`${this.baseUrl}/api/jobs/${jobId}/segments`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ segments } as UpdateSegmentsRequest),
    });
    
    if (!response.ok) {
      throw new Error(`Failed to update segments: ${response.statusText}`);
    }
    
    return response.json();
  }

  async deleteSegment(jobId: string, segmentId: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/jobs/${jobId}/segments/${segmentId}`, {
      method: 'DELETE',
    });
    
    if (!response.ok) {
      throw new Error(`Failed to delete segment: ${response.statusText}`);
    }
  }

  async getSegmentLogs(jobId: string, segmentId: string): Promise<{ logs: string[]; error?: string }> {
    const response = await fetch(`${this.baseUrl}/api/jobs/${jobId}/segments/${segmentId}/logs`);
    
    if (!response.ok) {
      throw new Error(`Failed to get logs: ${response.statusText}`);
    }
    
    return response.json();
  }

  getVideoUrl(jobId: string, segmentId: string): string {
    return `${this.baseUrl}/api/jobs/${jobId}/segments/${segmentId}/video`;
  }

  getFinalVideoUrl(jobId: string): string {
    return `${this.baseUrl}/api/jobs/${jobId}/final-video`;
  }

  async retrySegment(jobId: string, segmentId: string): Promise<{ status: string; segment_status: string; error?: string }> {
    const response = await fetch(`${this.baseUrl}/api/jobs/${jobId}/segments/${segmentId}/retry`, {
      method: 'POST',
    });
    
    if (!response.ok) {
      throw new Error(`Failed to retry segment: ${response.statusText}`);
    }
    
    return response.json();
  }

  async resumeJob(jobId: string): Promise<{ status: string; from_segment_index: number }> {
    const response = await fetch(`${this.baseUrl}/api/jobs/${jobId}/resume`, {
      method: 'POST',
    });
    
    if (!response.ok) {
      throw new Error(`Failed to resume job: ${response.statusText}`);
    }
    
    return response.json();
  }

  async testTTS(text?: string, voice?: string, speed?: number, stability?: number, similarityBoost?: number, seed?: number): Promise<{ audio_path: string; duration: number; audio_url: string }> {
    const response = await fetch(`${this.baseUrl}/api/test-tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice, speed, stability, similarity_boost: similarityBoost, seed: seed ?? null }),
    });
    
    if (!response.ok) {
      throw new Error(`TTS test failed: ${response.statusText}`);
    }
    
    return response.json();
  }

  getAudioUrl(audioUrl: string): string {
    return `${this.baseUrl}${audioUrl}`;
  }

  async getSegmentTypes(): Promise<{ types: Record<string, { label: string; description: string; icon: string }> }> {
    const response = await fetch(`${this.baseUrl}/api/segment-types`);
    if (!response.ok) {
      throw new Error(`Failed to get segment types: ${response.statusText}`);
    }
    return response.json();
  }

  async testSegment(
    type: string,
    description: string,
    voiceover?: { text: string; voice: string; speed: number },
    duration?: number
  ): Promise<{ job_id: string; segment_id: string }> {
    const response = await fetch(`${this.baseUrl}/api/test-segment`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, description, voiceover, duration }),
    });
    if (!response.ok) {
      throw new Error(`Segment test failed: ${response.statusText}`);
    }
    return response.json();
  }

  async previewPrompt(request: { isMaster?: boolean; prompt?: string; type?: string; description?: string; duration?: number }): Promise<{ prompt: string }> {
    const response = await fetch(`${this.baseUrl}/api/preview-prompt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!response.ok) {
      const errorMsg = await response.text();
      throw new Error(`Prompt preview failed: ${response.statusText} - ${errorMsg}`);
    }
    return response.json();
  }
}

export const api = new ApiService();
