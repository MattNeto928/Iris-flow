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

  async testTTS(text?: string, voice?: string, speed?: number): Promise<{ audio_path: string; duration: number; audio_url: string }> {
    const response = await fetch(`${this.baseUrl}/api/test-tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice, speed }),
    });
    
    if (!response.ok) {
      throw new Error(`TTS test failed: ${response.statusText}`);
    }
    
    return response.json();
  }

  getAudioUrl(audioUrl: string): string {
    return `${this.baseUrl}${audioUrl}`;
  }
}

export const api = new ApiService();
