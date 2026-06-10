import { useState, useEffect, useRef } from 'react';
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
  const [voice] = useState(segment.voiceover?.voice || 'xKhbyU7E3bC6T89Kn26c');
  const [speed, setSpeed] = useState(segment.voiceover?.speed || 1.15);
  const [logs, setLogs] = useState<string[]>(segment.logs || []);
  const [activeTab, setActiveTab] = useState<'edit' | 'logs' | 'debug'>('edit');
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  // Prevent background scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, []);

  // Poll logs during processing
  useEffect(() => {
    if (segment.status !== 'processing') return;
    const poll = async () => {
      try {
        const result = await api.getSegmentLogs(jobId, segment.id);
        setLogs(result.logs || []);
      } catch {}
    };
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [jobId, segment.id, segment.status]);

  // Auto-scroll logs
  useEffect(() => {
    if (activeTab === 'logs') {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, activeTab]);

  const handleSave = () => {
    onUpdate({
      title,
      description,
      type,
      voiceover: voiceoverText ? { text: voiceoverText, voice, speed } : undefined,
    });
    onClose();
  };

  const tabs = [
    { id: 'edit' as const, label: 'Edit' },
    ...(logs.length > 0 || segment.status === 'processing' ? [{ id: 'logs' as const, label: `Logs${logs.length ? ` (${logs.length})` : ''}` }] : []),
    ...(segment.llm_prompt ? [{ id: 'debug' as const, label: 'Debug' }] : []),
  ];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" style={{ maxWidth: 620 }} onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-medium text-zinc-100">
              Segment #{segment.order + 1}
            </h2>
            <p className="text-xs text-zinc-600 mt-0.5">{segment.id.slice(0, 8)}</p>
          </div>
          <button onClick={onClose} className="text-zinc-600 hover:text-zinc-300 transition-colors p-1 rounded hover:bg-white/5">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        {tabs.length > 1 && (
          <div className="flex gap-1 mb-4 border-b" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
            {tabs.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`text-xs px-3 py-2 transition-colors border-b-2 -mb-px ${
                  activeTab === tab.id
                    ? 'text-sky-400 border-sky-400'
                    : 'text-zinc-600 border-transparent hover:text-zinc-400'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}

        {/* Edit tab */}
        {activeTab === 'edit' && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] font-medium text-zinc-600 mb-1.5 uppercase tracking-wider">Title</label>
                <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} className="input-field text-sm" />
              </div>
              <div>
                <label className="block text-[10px] font-medium text-zinc-600 mb-1.5 uppercase tracking-wider">Type</label>
                <select
                  value={type}
                  onChange={(e) => setType(e.target.value as Segment['type'])}
                  className="input-field text-sm"
                >
                  <optgroup label="Visual Generation">
                    <option value="animation">Animation (Veo)</option>
                    <option value="grok">Grok (AI Generation)</option>
                    <option value="remotion">Remotion (React / 3D)</option>
                  </optgroup>
                  <optgroup label="Math & Science">
                    <option value="manim">Manim</option>
                    <option value="pysim">PySim</option>
                    <option value="stats">Stats</option>
                  </optgroup>
                  <optgroup label="Simulation">
                    <option value="mesa">Mesa (Agent-Based)</option>
                    <option value="pymunk">Pymunk (2D Physics)</option>
                    <option value="simpy">SimPy (Discrete Event)</option>
                  </optgroup>
                  <optgroup label="Data Visualization">
                    <option value="plotly">Plotly</option>
                    <option value="networkx">NetworkX</option>
                    <option value="audio">Audio</option>
                  </optgroup>
                  <optgroup label="Domain">
                    <option value="fractal">Fractal</option>
                    <option value="geo">Geo</option>
                    <option value="chem">Chem</option>
                    <option value="astro">Astro</option>
                  </optgroup>
                  <optgroup label="Other">
                    <option value="transition">Transition</option>
                  </optgroup>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-[10px] font-medium text-zinc-600 mb-1.5 uppercase tracking-wider">Description</label>
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} className="input-field text-sm min-h-[90px] resize-y" />
            </div>

            <div>
              <label className="block text-[10px] font-medium text-zinc-600 mb-1.5 uppercase tracking-wider">
                Voiceover script <span className="normal-case text-zinc-700">(optional)</span>
              </label>
              <textarea
                value={voiceoverText}
                onChange={(e) => setVoiceoverText(e.target.value)}
                placeholder="Enter narration... use ... for short pauses, ... ... for longer ones."
                className="input-field text-sm min-h-[70px] resize-y"
              />
              {voiceoverText && (
                <div className="mt-2 flex items-center gap-4" style={{ animation: 'slide-up 0.15s ease' }}>
                  <span className="text-[10px] text-zinc-600">Voice: Scientific Nipsey (ElevenLabs)</span>
                  <div className="flex items-center gap-2 flex-1">
                    <span className="text-[10px] text-zinc-700">Speed {speed}x</span>
                    <input
                      type="range" min="0.5" max="2.0" step="0.05" value={speed}
                      onChange={(e) => setSpeed(parseFloat(e.target.value))}
                      className="flex-1 h-1 rounded cursor-pointer accent-sky-400"
                      style={{ background: 'var(--color-surface-300)' }}
                    />
                  </div>
                </div>
              )}
            </div>

            {segment.error && (
              <div className="p-3 rounded-lg text-sm text-red-400" style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}>
                {segment.error}
              </div>
            )}
          </div>
        )}

        {/* Logs tab */}
        {activeTab === 'logs' && (
          <div>
            {segment.status === 'processing' && (
              <div className="flex items-center gap-2 mb-3">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-400" />
                </span>
                <span className="text-xs text-amber-400">Processing — live output</span>
              </div>
            )}
            <div className="log-terminal" style={{ maxHeight: '340px' }}>
              {logs.length === 0 ? (
                <span className="text-zinc-700">No output yet...</span>
              ) : (
                logs.map((line, i) => (
                  <div key={i}>
                    <span className="text-zinc-700 select-none">&gt; </span>
                    <span className="text-zinc-400">{line}</span>
                  </div>
                ))
              )}
              <div ref={logsEndRef} />
            </div>
          </div>
        )}

        {/* Debug tab */}
        {activeTab === 'debug' && segment.llm_prompt && (
          <div className="space-y-3">
            <div>
              <p className="text-[10px] text-zinc-600 uppercase tracking-wider mb-1.5">Model</p>
              <p className="text-sm text-zinc-300 font-mono">{segment.llm_model || '—'}</p>
            </div>
            <div>
              <p className="text-[10px] text-zinc-600 uppercase tracking-wider mb-1.5">Generation prompt</p>
              <pre className="log-terminal whitespace-pre-wrap text-zinc-500" style={{ maxHeight: '300px' }}>
                {segment.llm_prompt}
              </pre>
            </div>
            {segment.generated_script && (
              <div>
                <p className="text-[10px] text-zinc-600 uppercase tracking-wider mb-1.5">Generated code</p>
                <pre className="log-terminal whitespace-pre-wrap" style={{ maxHeight: '200px' }}>
                  <code className="text-zinc-400">{segment.generated_script}</code>
                </pre>
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="flex justify-end gap-2 mt-5 pt-4 border-t" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          {activeTab === 'edit' && (
            <button onClick={handleSave} className="btn-primary text-sm">Save changes</button>
          )}
        </div>
      </div>
    </div>
  );
}
