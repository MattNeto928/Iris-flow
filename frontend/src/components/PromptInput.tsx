import { useState } from 'react';

interface PromptInputProps {
  onSubmit: (prompt: string, voice?: string, speed?: number) => void;
  isLoading: boolean;
}

export function PromptInput({ onSubmit, isLoading }: PromptInputProps) {
  const [prompt, setPrompt] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [voice, setVoice] = useState('Fenrir');
  const [speed, setSpeed] = useState(1.15);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (prompt.trim() && !isLoading) {
      onSubmit(prompt.trim(), voice, speed);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="w-full">
      <div className="glass-card p-4">
        <label htmlFor="prompt" className="block text-sm font-medium text-gray-300 mb-2">
          Describe your video
        </label>
        <textarea
          id="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Create a 2-minute educational video about black holes. Start with an animation of space, then show the mathematical equations for gravitational pull using Manim, followed by a particle simulation showing matter being pulled into the event horizon..."
          className="input-field min-h-[120px] resize-y"
          disabled={isLoading}
        />

        {/* Advanced Options Toggle */}
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="text-xs text-gray-400 hover:text-white flex items-center gap-1 transition-colors"
          >
            <svg 
              className={`w-3 h-3 transition-transform ${showAdvanced ? 'rotate-90' : ''}`} 
              fill="none" 
              viewBox="0 0 24 24" 
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            Advanced Options (Voice & Speed)
          </button>

          {showAdvanced && (
            <div className="mt-3 grid grid-cols-2 gap-4 p-3 bg-surface-50 rounded-lg animate-in fade-in slide-in-from-top-2 border border-white/5">
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1">Default Voice</label>
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
                  Default Speed: {speed}x
                </label>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-gray-500">0.5x</span>
                  <input
                    type="range"
                    min="0.5"
                    max="2.0"
                    step="0.05"
                    value={speed}
                    onChange={(e) => setSpeed(parseFloat(e.target.value))}
                    className="flex-1 h-1.5 bg-surface-300 rounded-lg appearance-none cursor-pointer accent-iris-500"
                  />
                  <span className="text-[10px] text-gray-500">2.0x</span>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="mt-4 flex items-center justify-between">
          <p className="text-xs text-gray-500">
            Be detailed about the visual style, segments, and narration you want.
          </p>
          <button
            type="submit"
            disabled={!prompt.trim() || isLoading}
            className="btn-primary flex items-center gap-2"
          >
            {isLoading ? (
              <>
                <LoadingSpinner />
                Generating...
              </>
            ) : (
              <>
                <SparklesIcon />
                Generate Segments
              </>
            )}
          </button>
        </div>
      </div>
    </form>
  );
}

function LoadingSpinner() {
  return (
    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
        fill="none"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}

function SparklesIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"
      />
    </svg>
  );
}
