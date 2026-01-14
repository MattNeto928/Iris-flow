import { useState, useEffect } from 'react';
import type { Segment } from '../types';
import { api } from '../services/api';

interface SegmentEditorProps {
  segment: Segment;
  jobId: string;
  onClose: () => void;
  onUpdate: (updates: Partial<Segment>) => void;
}

export function SegmentEditor({ segment, jobId, onClose, onUpdate }: SegmentEditorProps) {
  const [title, setTitle] = useState(segment.title);
  const [description, setDescription] = useState(segment.description);
  const [type, setType] = useState(segment.type);
  const [voiceoverText, setVoiceoverText] = useState(segment.voiceover?.text || '');
  const [voice, setVoice] = useState(segment.voiceover?.voice || 'Fenrir');
  const [speed, setSpeed] = useState(segment.voiceover?.speed || 1.15);
  const [logs, setLogs] = useState<string[]>(segment.logs || []);

  // Fetch logs periodically during processing
  useEffect(() => {
    if (segment.status === 'processing') {
      const interval = setInterval(async () => {
        try {
          const result = await api.getSegmentLogs(jobId, segment.id);
          setLogs(result.logs);
        } catch (err) {
          console.error('Failed to fetch logs:', err);
        }
      }, 2000);
      return () => clearInterval(interval);
    }
  }, [jobId, segment.id, segment.status]);

  const handleSave = () => {
    onUpdate({
      title,
      description,
      type,
      voiceover: voiceoverText ? { 
        text: voiceoverText,
        voice,
        speed
      } : undefined,
    });
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">Edit Segment #{segment.order + 1}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Form */}
        <div className="space-y-4">
          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="input-field"
            />
          </div>

          {/* Type */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Type</label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as Segment['type'])}
              className="input-field"
            >
              <option value="animation">Animation (Veo 3.1)</option>
              <option value="manim">Manim (Math Visualization)</option>
              <option value="pysim">PySim (Scientific Simulation)</option>
            </select>
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="input-field min-h-[100px]"
            />
          </div>

          {/* Voiceover */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Voiceover Script (optional)
            </label>
            <textarea
              value={voiceoverText}
              onChange={(e) => setVoiceoverText(e.target.value)}
              placeholder="Enter narration text..."
              className="input-field min-h-[80px]"
            />
            
            {/* Voice & Speed Controls */}
            {voiceoverText && (
              <div className="mt-3 grid grid-cols-2 gap-4 animate-in fade-in slide-in-from-top-2">
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1">Voice</label>
                  <select
                    value={voice}
                    onChange={(e) => setVoice(e.target.value)}
                    className="w-full bg-surface-200 border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-iris-500"
                  >
                    <option value="Schedar">Schedar (Male)</option>
                    <option value="Kore">Kore (Female)</option>
                    <option value="Charon">Charon (Male Deep)</option>
                    <option value="Fenrir">Fenrir (Male Fast)</option>
                    <option value="Aoede">Aoede (Female Soft)</option>
                    <option value="Puck">Puck (Female Energetic)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1">
                    Speed: {speed}x
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      type="range"
                      min="0.5"
                      max="2.0"
                      step="0.05"
                      value={speed}
                      onChange={(e) => setSpeed(parseFloat(e.target.value))}
                      className="flex-1 h-1.5 bg-surface-300 rounded-lg appearance-none cursor-pointer accent-iris-500"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Logs Section (visible during/after processing) */}
          {(segment.status !== 'pending' && logs.length > 0) && (
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">
                Processing Logs
              </label>
              <div className="bg-surface-50 border border-surface-300 rounded-lg p-3 max-h-[200px] overflow-auto">
                {logs.map((log, i) => (
                  <div key={i} className="text-xs font-mono text-gray-400 mb-1">
                    {log}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Error display */}
          {segment.error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
              <p className="text-sm text-red-400">{segment.error}</p>
            </div>
          )}

          {/* JSON Preview */}
          <details className="mt-4">
            <summary className="text-sm text-gray-500 cursor-pointer hover:text-gray-400">
              View Raw JSON
            </summary>
            <pre className="mt-2 bg-surface-50 p-3 rounded text-xs overflow-auto max-h-[200px]">
              {JSON.stringify(segment, null, 2)}
            </pre>
          </details>
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-3 mt-6 pt-4 border-t border-surface-300">
          <button onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button onClick={handleSave} className="btn-primary">
            Save Changes
          </button>
        </div>
      </div>
    </div>
  );
}
