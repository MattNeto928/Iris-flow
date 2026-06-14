import { useState } from 'react';
import { api } from '../services/api';

interface PromptInputProps {
  onSubmit: (prompt: string, voice?: string, speed?: number) => void;
  isLoading: boolean;
}

export function PromptInput({ onSubmit, isLoading }: PromptInputProps) {
  const [prompt, setPrompt] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [voice] = useState('xKhbyU7E3bC6T89Kn26c');
  const [speed, setSpeed] = useState(1.0);
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (prompt.trim() && !isLoading) {
      setPreviewText(null);
      onSubmit(prompt.trim(), voice, speed);
    }
  };

  const handlePreview = async () => {
    if (!prompt.trim() || isPreviewing) return;
    setIsPreviewing(true);
    setPreviewError(null);
    try {
      const res = await api.previewPrompt({ isMaster: true, prompt: prompt.trim() });
      setPreviewText(res.prompt);
    } catch (err: any) {
      setPreviewError(err.message || 'Error fetching preview');
    } finally {
      setIsPreviewing(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="w-full">
      <div className="glass-card p-4">
        <label htmlFor="prompt" className="block text-xs font-medium text-zinc-400 uppercase tracking-widest mb-2">
          Describe your video
        </label>
        <textarea
          id="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Create a 2-minute educational video about black holes. Start with a Manim animation of spacetime curvature, then show particle simulation of matter approaching the event horizon..."
          className="input-field min-h-[100px] resize-y text-sm"
          disabled={isLoading}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit(e as any);
          }}
        />

        {/* Advanced toggle */}
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="mt-2 text-[11px] text-zinc-600 hover:text-zinc-400 flex items-center gap-1 transition-colors"
        >
          <svg className={`w-3 h-3 transition-transform duration-200 ${showAdvanced ? 'rotate-90' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          Advanced options
        </button>

        {showAdvanced && (
          <div className="mt-3 p-3 rounded-lg border" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.07)', animation: 'slide-up 0.15s ease' }}>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-[10px] font-medium text-zinc-600 mb-1.5 uppercase tracking-wider">Voice</label>
                <select
                  value={voice}
                  className="w-full text-xs rounded-md px-2 py-1.5 text-zinc-200 focus:outline-none"
                  style={{ background: 'var(--color-surface-200)', border: '1px solid rgba(255,255,255,0.1)' }}
                >
                  <option value="xKhbyU7E3bC6T89Kn26c">Scientific Nipsey (ElevenLabs)</option>
                </select>
              </div>
              <div>
                <label className="block text-[10px] font-medium text-zinc-600 mb-1.5 uppercase tracking-wider">
                  Speed — {speed}x
                </label>
                <div className="flex items-center gap-2 mt-2">
                  <span className="text-[10px] text-zinc-700">0.5x</span>
                  <input
                    type="range" min="0.5" max="2.0" step="0.05" value={speed}
                    onChange={(e) => setSpeed(parseFloat(e.target.value))}
                    className="flex-1 h-1 rounded-full cursor-pointer accent-sky-400"
                    style={{ background: 'var(--color-surface-300)' }}
                  />
                  <span className="text-[10px] text-zinc-700">2.0x</span>
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="mt-3 flex items-center justify-between">
          <p className="text-[11px] text-zinc-700">
            Cmd+Enter to generate
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handlePreview}
              disabled={!prompt.trim() || isPreviewing || isLoading}
              className="btn-secondary text-xs py-1.5 px-3"
            >
              {isPreviewing ? (
                <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              )}
              Preview prompt
            </button>
            <button
              type="submit"
              disabled={!prompt.trim() || isLoading}
              className="btn-primary text-xs py-1.5 px-4"
            >
              {isLoading ? (
                <>
                  <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Generating segments...
                </>
              ) : (
                <>
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  Generate segments
                </>
              )}
            </button>
          </div>
        </div>

        {previewError && (
          <div className="mt-3 p-2.5 rounded-lg text-xs text-red-400" style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}>
            {previewError}
          </div>
        )}

        {previewText && (
          <div className="mt-3" style={{ animation: 'slide-up 0.15s ease' }}>
            <details open>
              <summary className="text-[10px] text-zinc-600 cursor-pointer hover:text-zinc-400 select-none transition-colors uppercase tracking-wider">
                Master prompt preview (claude-opus-4-8)
              </summary>
              <pre className="mt-2 log-terminal whitespace-pre-wrap text-zinc-500 max-h-[240px]">
                {previewText}
              </pre>
            </details>
          </div>
        )}
      </div>
    </form>
  );
}
