import { useState, useCallback, useEffect, useRef } from 'react';
import type { Segment, GenerationJob } from '../types';
import { api } from '../services/api';

export function useSegments() {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Generate segments from a prompt
  const generateFromPrompt = useCallback(async (prompt: string, voice?: string, speed?: number) => {
    setIsLoading(true);
    setError(null);
    
    try {
      const response = await api.generateSegments(prompt, voice, speed);
      
      // Assign positions for visual layout
      const segmentsWithPositions = response.segments.map((seg, index) => ({
        ...seg,
        position: {
          x: 100 + (index % 3) * 450,
          y: 150 + Math.floor(index / 3) * 350,
        },
      }));
      
      setSegments(segmentsWithPositions);
      
      // Create a job for these segments
      const newJob = await api.createJob(response.segments);
      setJob(newJob);
      
      return response.segments;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate segments');
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Update a segment
  const updateSegment = useCallback((segmentId: string, updates: Partial<Segment>) => {
    setSegments(prev => prev.map(seg => 
      seg.id === segmentId ? { ...seg, ...updates } : seg
    ));
  }, []);

  // Delete a segment
  const deleteSegment = useCallback(async (segmentId: string) => {
    if (job) {
      try {
        await api.deleteSegment(job.id, segmentId);
      } catch (err) {
        console.error('Failed to delete segment from server:', err);
      }
    }
    
    setSegments(prev => {
      const filtered = prev.filter(seg => seg.id !== segmentId);
      // Reorder
      return filtered.map((seg, index) => ({ ...seg, order: index }));
    });
  }, [job]);

  // Reorder segments
  const reorderSegments = useCallback((fromIndex: number, toIndex: number) => {
    setSegments(prev => {
      const newSegments = [...prev];
      const [moved] = newSegments.splice(fromIndex, 1);
      newSegments.splice(toIndex, 0, moved);
      
      // Update order numbers
      return newSegments.map((seg, index) => ({ ...seg, order: index }));
    });
  }, []);

  // Move segment position (for drag and drop on canvas)
  const moveSegment = useCallback((segmentId: string, x: number, y: number) => {
    setSegments(prev => prev.map(seg =>
      seg.id === segmentId ? { ...seg, position: { x, y } } : seg
    ));
  }, []);

  // Start video generation
  const startGeneration = useCallback(async () => {
    if (!job) {
      setError('No job created yet');
      return;
    }

    try {
      // Update job with current segment state
      await api.updateJobSegments(job.id, segments);
      
      // Start the job
      await api.startJob(job.id);
      
      // Start polling for updates
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start generation');
    }
  }, [job, segments]);

  // Pause generation
  const pauseGeneration = useCallback(async () => {
    if (!job) return;
    
    try {
      await api.pauseJob(job.id);
      stopPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to pause generation');
    }
  }, [job]);

  // Poll for job updates
  const startPolling = useCallback(() => {
    if (pollingRef.current) return;
    
    pollingRef.current = setInterval(async () => {
      if (!job) return;
      
      try {
        const updatedJob = await api.getJob(job.id);
        setJob(updatedJob);
        
        // Update local segments with server state
        setSegments(prev => prev.map(seg => {
          const serverSeg = updatedJob.segments.find(s => s.id === seg.id);
          if (serverSeg) {
            return { ...seg, ...serverSeg, position: seg.position };
          }
          return seg;
        }));
        
        // Stop polling if job is done
        if (['completed', 'failed', 'paused'].includes(updatedJob.status)) {
          stopPolling();
        }
      } catch (err) {
        console.error('Polling error:', err);
      }
    }, 2000);
  }, [job]);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  return {
    segments,
    job,
    isLoading,
    error,
    generateFromPrompt,
    updateSegment,
    deleteSegment,
    reorderSegments,
    moveSegment,
    startGeneration,
    pauseGeneration,
    startPolling,
    setError,
  };
}
