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
  animation: 'Animation',
  manim: 'Manim',
  pysim: 'PySim',
  transition: 'Transition',
};

const typeColors: Record<string, string> = {
  animation: 'badge-animation',
  manim: 'badge-manim',
  pysim: 'badge-pysim',
  transition: 'badge-transition',
};

const statusColors: Record<string, string> = {
  pending: 'segment-pending',
  processing: 'segment-processing',
  completed: 'segment-completed',
  failed: 'segment-failed',
};

export function SegmentNode({ segment, onClick, onDelete, onRetry, onViewCode, isSelected, isRetrying }: SegmentNodeProps) {
  const statusClass = statusColors[segment.status] || 'segment-pending';
  const typeClass = typeColors[segment.type] || 'badge-animation';
  
  return (
    <div
      className={`
        glass-card border-2 p-4 cursor-pointer transition-all duration-200
        hover:scale-[1.02] hover:shadow-lg
        ${statusClass}
        ${isSelected ? 'ring-2 ring-iris-500 ring-offset-2 ring-offset-surface-50' : ''}
      `}
      style={{ width: 280 }}
      onClick={onClick}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 font-mono">
            #{segment.order + 1}
          </span>
          <span className={`text-xs px-2 py-0.5 rounded-full text-white font-medium ${typeClass}`}>
            {typeLabels[segment.type]}
          </span>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="text-gray-500 hover:text-red-400 transition-colors p-1"
          title="Delete segment"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Title */}
      <h3 className="font-semibold text-white mb-1 line-clamp-1">
        {segment.title}
      </h3>

      {/* Description */}
      <p className="text-sm text-gray-400 line-clamp-2 mb-3">
        {segment.description}
      </p>

      {/* Footer */}
      <div className="flex items-center justify-between text-xs">
        {/* Voiceover indicator */}
        {segment.voiceover ? (
          <span className="flex items-center gap-1 text-iris-400">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
            Voiceover
          </span>
        ) : (
          <span className="text-gray-600">No voiceover</span>
        )}

        {/* Status indicator */}
        <StatusBadge status={segment.status} />
      </div>

      {/* Duration (if available) */}
      {segment.duration_seconds && (
        <div className="mt-2 pt-2 border-t border-white/10 text-xs text-gray-500">
          Duration: {segment.duration_seconds.toFixed(1)}s
        </div>
      )}

      {/* View Code button for pysim/manim */}
      {segment.generated_script && onViewCode && (
        <div className="mt-2 pt-2 border-t border-white/10">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onViewCode();
            }}
            className="text-xs text-iris-400 hover:text-iris-300 flex items-center gap-1 w-full justify-center py-1 rounded hover:bg-white/5 transition-colors"
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
            </svg>
            View Generated Code
          </button>
        </div>
      )}

      {/* Error message with retry button */}
      {segment.error && (
        <div className="mt-2 pt-2 border-t border-red-500/30">
          <p className="text-xs text-red-400 line-clamp-2 mb-2">
            Error: {segment.error}
          </p>
          {onRetry && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onRetry();
              }}
              disabled={isRetrying}
              className="w-full px-3 py-1.5 text-xs font-medium rounded-md bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {isRetrying ? (
                <>
                  <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Retrying...
                </>
              ) : (
                <>
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  Retry Segment
                </>
              )}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const statusConfig: Record<string, { label: string; className: string }> = {
    pending: { label: 'Pending', className: 'text-gray-500' },
    processing: { label: 'Processing...', className: 'text-yellow-500' },
    completed: { label: 'Complete', className: 'text-green-500' },
    failed: { label: 'Failed', className: 'text-red-500' },
  };

  const config = statusConfig[status] || statusConfig.pending;

  return (
    <span className={`flex items-center gap-1 ${config.className}`}>
      {status === 'processing' && (
        <span className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />
      )}
      {status === 'completed' && (
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      )}
      {config.label}
    </span>
  );
}
