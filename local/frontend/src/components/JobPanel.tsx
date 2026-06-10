import { useState, useEffect, useRef } from 'react';
import type { GenerationJob, Segment } from '../types';
import { api } from '../services/api';

interface JobPanelProps {
  job: GenerationJob;
  segments: Segment[];
  isGenerating: boolean;
  canStart: boolean;
  onPause: () => void;
  onStart: () => void;
  onRetrySegment: (segmentId: string) => void;
  onViewVideo: (segmentId: string) => void;
  onViewCode: (segmentId: string) => void;
  onClearJob: () => void;
  retryingSegmentId?: string;
}

const typeLabels: Record<string, string> = {
  animation: 'Animation', manim: 'Manim', pysim: 'PySim', transition: 'Transition',
  mesa: 'Mesa', pymunk: 'Pymunk', simpy: 'SimPy', plotly: 'Plotly',
  networkx: 'NetworkX', audio: 'Audio', stats: 'Stats', fractal: 'Fractal',
  geo: 'Geo', chem: 'Chem', astro: 'Astro', grok: 'Grok', remotion: 'Remotion',
};

const typeColors: Record<string, string> = {
  animation: 'badge-animation', manim: 'badge-manim', pysim: 'badge-pysim',
  transition: 'badge-transition', mesa: 'badge-mesa', pymunk: 'badge-pymunk',
  simpy: 'badge-simpy', plotly: 'badge-plotly', networkx: 'badge-networkx',
  audio: 'badge-audio', stats: 'badge-stats', fractal: 'badge-fractal',
  geo: 'badge-geo', chem: 'badge-chem', astro: 'badge-astro', grok: 'badge-grok',
  remotion: 'badge-remotion',
};

function StatusDot({ status }: { status: string }) {
  if (status === 'processing') {
    return (
      <span className="relative flex h-2 w-2 mr-1.5 shrink-0">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-400" />
      </span>
    );
  }
  const colors: Record<string, string> = {
    pending: 'bg-zinc-600', completed: 'bg-emerald-500', failed: 'bg-red-500',
  };
  return <span className={`inline-flex h-2 w-2 rounded-full mr-1.5 shrink-0 ${colors[status] || 'bg-zinc-600'}`} />;
}

interface SegmentRowProps {
  segment: Segment;
  jobId: string;
  index: number;
  isExpanded: boolean;
  onToggle: () => void;
  isActive: boolean;
  activeLogs: string[];
  logsEndRef: React.RefObject<HTMLDivElement>;
  onRetry?: () => void;
  onViewVideo?: () => void;
  onViewCode?: () => void;
  isRetrying?: boolean;
}

function SegmentRow({
  segment, index, isExpanded, onToggle, isActive,
  activeLogs, logsEndRef, onRetry, onViewVideo, onViewCode, isRetrying,
}: SegmentRowProps) {
  const rowClass = isActive ? 'active' : segment.status === 'completed' ? 'done' : segment.status === 'failed' ? 'error' : '';
  const logs = isActive ? activeLogs : (segment.logs || []);

  return (
    <div className="mb-1">
      <button
        onClick={onToggle}
        className={`seg-row w-full text-left flex items-start gap-2.5 ${rowClass}`}
      >
        {/* Order number */}
        <span className="text-[10px] font-mono text-zinc-600 w-4 shrink-0 mt-0.5">{String(index + 1).padStart(2, '0')}</span>

        {/* Status dot */}
        <div className="mt-1"><StatusDot status={segment.status} /></div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
            <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded text-white ${typeColors[segment.type] || 'badge-animation'}`}>
              {typeLabels[segment.type] || segment.type}
            </span>
            <span className="text-[11px] font-medium text-zinc-200 truncate">{segment.title}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`text-[10px] ${
              segment.status === 'completed' ? 'text-emerald-400' :
              segment.status === 'failed' ? 'text-red-400' :
              segment.status === 'processing' ? 'text-amber-400' : 'text-zinc-600'
            }`}>
              {segment.status === 'processing' ? 'Generating...' :
               segment.status === 'completed' ? `Done${segment.duration_seconds ? ` · ${segment.duration_seconds.toFixed(1)}s` : ''}` :
               segment.status === 'failed' ? 'Failed' : 'Pending'}
            </span>
          </div>
        </div>

        {/* Chevron */}
        <svg
          className={`w-3.5 h-3.5 text-zinc-600 shrink-0 mt-0.5 transition-transform duration-200 ${isExpanded ? 'rotate-90' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </button>

      {/* Expanded detail */}
      {isExpanded && (
        <div className="mt-1 ml-9 space-y-2 pb-2" style={{ animation: 'slide-up 0.15s ease' }}>
          {segment.description && (
            <p className="text-[10px] text-zinc-500 leading-relaxed">{segment.description}</p>
          )}

          {/* Error */}
          {segment.error && (
            <div className="bg-red-500/10 border border-red-500/20 rounded p-2">
              <p className="text-[10px] text-red-400 font-mono">{segment.error}</p>
            </div>
          )}

          {/* Logs */}
          {(logs.length > 0 || isActive) && (
            <div className="log-terminal">
              {logs.length === 0 ? (
                <span className="text-zinc-700">Waiting for output...</span>
              ) : (
                logs.map((line, i) => (
                  <div key={i} className="text-zinc-400">
                    <span className="text-zinc-700 select-none">&gt; </span>{line}
                  </div>
                ))
              )}
              <div ref={logsEndRef} />
            </div>
          )}

          {/* Actions row */}
          <div className="flex items-center gap-1.5 flex-wrap">
            {onViewVideo && (
              <button onClick={(e) => { e.stopPropagation(); onViewVideo(); }} className="btn-ghost">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                View clip
              </button>
            )}
            {onViewCode && (
              <button onClick={(e) => { e.stopPropagation(); onViewCode(); }} className="btn-ghost">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                </svg>
                View code
              </button>
            )}
            {onRetry && (
              <button
                onClick={(e) => { e.stopPropagation(); onRetry(); }}
                disabled={isRetrying}
                className="btn-ghost text-amber-500 hover:text-amber-400"
              >
                {isRetrying ? (
                  <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                ) : (
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                )}
                {isRetrying ? 'Retrying...' : 'Retry'}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function JobPanel({
  job, segments, isGenerating, canStart,
  onPause, onStart, onRetrySegment, onViewVideo, onViewCode, onClearJob, retryingSegmentId,
}: JobPanelProps) {
  const [expandedSegId, setExpandedSegId] = useState<string | null>(null);
  const [activeLogs, setActiveLogs] = useState<string[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

  const sortedSegments = [...segments].sort((a, b) => a.order - b.order);
  const activeSegment = sortedSegments.find(s => s.status === 'processing');
  const completedCount = segments.filter(s => s.status === 'completed').length;
  const failedCount = segments.filter(s => s.status === 'failed').length;
  const progress = segments.length > 0 ? (completedCount / segments.length) * 100 : 0;

  // Auto-expand the active (processing) segment
  useEffect(() => {
    if (activeSegment) setExpandedSegId(activeSegment.id);
  }, [activeSegment?.id]);

  // Poll logs for the active segment
  useEffect(() => {
    if (!activeSegment) { setActiveLogs([]); return; }
    const poll = async () => {
      try {
        const result = await api.getSegmentLogs(job.id, activeSegment.id);
        setActiveLogs(result.logs || []);
      } catch {}
    };
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [job.id, activeSegment?.id]);


  const jobStatusLabel: Record<string, string> = {
    idle: 'Ready', running: 'Running', paused: 'Paused', completed: 'Complete', failed: 'Failed',
  };
  const jobStatusColor: Record<string, string> = {
    idle: 'text-zinc-500', running: 'text-amber-400', paused: 'text-zinc-400',
    completed: 'text-emerald-400', failed: 'text-red-400',
  };

  return (
    <aside
      className="job-panel-enter w-[340px] shrink-0 flex flex-col border-l"
      style={{
        background: 'rgba(255,255,255,0.015)',
        borderColor: 'rgba(255,255,255,0.07)',
      }}
    >
      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
        <div className="flex items-start justify-between mb-3">
          <div>
            <h2 className="text-sm font-medium text-zinc-100 leading-none mb-1">Active Job</h2>
            <span className="text-[10px] font-mono text-zinc-600">#{job.id.slice(0, 8)}</span>
          </div>
          <button
            onClick={onClearJob}
            title="Clear job"
            className="text-zinc-600 hover:text-zinc-300 transition-colors p-1 rounded hover:bg-white/5"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Progress bar */}
        <div className="progress-track mb-2">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>

        {/* Status row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {isGenerating && (
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-amber-400" />
              </span>
            )}
            <span className={`text-xs font-medium ${jobStatusColor[job.status] || 'text-zinc-500'}`}>
              {jobStatusLabel[job.status] || job.status}
            </span>
          </div>
          <span className="text-[10px] text-zinc-600">
            {completedCount}/{segments.length} done
            {failedCount > 0 && <span className="text-red-500 ml-1.5">{failedCount} failed</span>}
          </span>
        </div>
      </div>

      {/* Actions */}
      <div className="px-4 py-3 flex items-center gap-2 border-b" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
        {job.status === 'completed' ? (
          <a href={api.getFinalVideoUrl(job.id)} download className="btn-primary flex-1 justify-center">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            Download video
          </a>
        ) : isGenerating ? (
          <button onClick={onPause} className="btn-secondary flex-1 justify-center">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 9v6m4-6v6" />
            </svg>
            Pause
          </button>
        ) : (
          <button onClick={onStart} disabled={!canStart} className="btn-primary flex-1 justify-center">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
            </svg>
            {job.status === 'paused' ? 'Resume' : 'Generate'}
          </button>
        )}
      </div>

      {/* Segment list */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-0.5">
        <p className="section-label mb-2">Segments</p>
        {sortedSegments.map((seg, i) => (
          <SegmentRow
            key={seg.id}
            segment={seg}
            jobId={job.id}
            index={i}
            isExpanded={expandedSegId === seg.id}
            onToggle={() => setExpandedSegId(expandedSegId === seg.id ? null : seg.id)}
            isActive={seg.id === activeSegment?.id}
            activeLogs={activeLogs}
            logsEndRef={logsEndRef}
            onRetry={seg.status === 'failed' ? () => onRetrySegment(seg.id) : undefined}
            onViewVideo={seg.status === 'completed' ? () => onViewVideo(seg.id) : undefined}
            onViewCode={seg.generated_script ? () => onViewCode(seg.id) : undefined}
            isRetrying={retryingSegmentId === seg.id}
          />
        ))}
      </div>

      {/* LLM prompt (if available) */}
      {job.llm_prompt && (
        <div className="px-3 pb-3 border-t mt-auto pt-3" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          <details>
            <summary className="text-[10px] text-zinc-600 cursor-pointer hover:text-zinc-400 select-none transition-colors">
              Master prompt ({job.llm_model || 'claude-opus-4-7'})
            </summary>
            <pre className="mt-2 log-terminal whitespace-pre-wrap text-zinc-500 max-h-[120px]">
              {job.llm_prompt}
            </pre>
          </details>
        </div>
      )}
    </aside>
  );
}
