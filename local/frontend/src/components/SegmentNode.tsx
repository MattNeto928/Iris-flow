import type { Segment } from '../types';

interface SegmentNodeProps {
  segment: Segment;
  onClick: () => void;
  onDelete: () => void;
  onRetry?: () => void;
  onViewCode?: () => void;
  isSelected?: boolean;
  isRetrying?: boolean;
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

const statusBorderClass: Record<string, string> = {
  pending: 'segment-pending',
  processing: 'segment-processing',
  completed: 'segment-completed',
  failed: 'segment-failed',
};

export function SegmentNode({ segment, onClick, onDelete, onRetry, onViewCode, isSelected, isRetrying }: SegmentNodeProps) {
  const borderClass = statusBorderClass[segment.status] || 'segment-pending';

  return (
    <div
      className={`
        glass-card border-2 p-3.5 cursor-pointer group
        transition-all duration-200 hover:shadow-lg hover:border-opacity-80
        ${borderClass}
        ${isSelected ? 'ring-2 ring-sky-400 ring-offset-2 ring-offset-[#09090b]' : ''}
      `}
      style={{ width: 272 }}
      onClick={onClick}
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-zinc-700">#{segment.order + 1}</span>
          <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded text-white ${typeColors[segment.type] || 'badge-animation'}`}>
            {typeLabels[segment.type] || segment.type}
          </span>
        </div>

        {/* Actions (always visible, subtle) */}
        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
          {onViewCode && (
            <button
              onClick={(e) => { e.stopPropagation(); onViewCode(); }}
              className="p-1 rounded text-zinc-600 hover:text-sky-400 hover:bg-white/5 transition-colors"
              title="View generated code"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
              </svg>
            </button>
          )}
          {onRetry && (
            <button
              onClick={(e) => { e.stopPropagation(); onRetry(); }}
              disabled={isRetrying}
              className="p-1 rounded text-zinc-600 hover:text-amber-400 hover:bg-white/5 transition-colors disabled:opacity-40"
              title="Retry segment"
            >
              {isRetrying ? (
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              )}
            </button>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="p-1 rounded text-zinc-600 hover:text-red-400 hover:bg-white/5 transition-colors"
            title="Delete segment"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </div>

      {/* Title */}
      <h3 className="text-sm font-medium text-zinc-100 mb-1 line-clamp-1 leading-snug">
        {segment.title}
      </h3>

      {/* Description */}
      <p className="text-xs text-zinc-500 line-clamp-2 leading-relaxed mb-3">
        {segment.description}
      </p>

      {/* Footer */}
      <div className="flex items-center justify-between text-[10px]">
        <span className={`flex items-center gap-1 ${
          segment.voiceover ? 'text-sky-400/70' : 'text-zinc-700'
        }`}>
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
          </svg>
          {segment.voiceover ? 'Voiceover' : 'No voiceover'}
        </span>

        <StatusLabel status={segment.status} duration={segment.duration_seconds} />
      </div>
    </div>
  );
}

function StatusLabel({ status, duration }: { status: string; duration?: number }) {
  if (status === 'processing') {
    return (
      <span className="flex items-center gap-1 text-amber-400">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
        Generating
      </span>
    );
  }
  if (status === 'completed') {
    return (
      <span className="flex items-center gap-1 text-emerald-400">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
        </svg>
        {duration ? `${duration.toFixed(1)}s` : 'Done'}
      </span>
    );
  }
  if (status === 'failed') {
    return (
      <span className="flex items-center gap-1 text-red-400">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
        Failed
      </span>
    );
  }
  return <span className="text-zinc-700">Pending</span>;
}
