import { useState, useEffect, useCallback } from 'react';
import { useSegments } from './hooks/useSegments';
import { PromptInput } from './components/PromptInput';
import { Canvas } from './components/Canvas';
import { SegmentEditor } from './components/SegmentEditor';
import { VideoPreview } from './components/VideoPreview';
import { CodeModal } from './components/CodeModal';
import { JobPanel } from './components/JobPanel';
import type { Segment, GenerationJob } from './types';
import { api } from './services/api';

const FALLBACK_DEFAULTS: Record<string, { label: string; description: string }> = {
  pysim:      { label: 'PySim',     description: 'Simulate a chaotic double pendulum with trails' },
  manim:      { label: 'Manim',     description: "Animate Euler's identity on the complex plane" },
  animation:  { label: 'Animation', description: 'Cinematic flythrough of a deep-sea cave' },
  mesa:       { label: 'Mesa',      description: 'Predator-prey agent-based simulation' },
  pymunk:     { label: 'Pymunk',    description: "Newton's cradle with momentum transfer" },
  simpy:      { label: 'SimPy',     description: 'Multi-server queueing system' },
  plotly:     { label: 'Plotly',    description: '3D surface of the Rosenbrock function' },
  networkx:   { label: 'NetworkX',  description: "Dijkstra's shortest path animation" },
  audio:      { label: 'Audio',     description: 'Harmonic series frequency visualization' },
  stats:      { label: 'Stats',     description: 'Central Limit Theorem dice simulation' },
  fractal:    { label: 'Fractal',   description: 'Mandelbrot set boundary zoom' },
  geo:        { label: 'Geo',       description: 'Internet spread across the globe 1990–2024' },
  chem:       { label: 'Chem',      description: 'Caffeine molecule rotation' },
  astro:      { label: 'Astro',     description: 'Inner solar system orbital mechanics' },
  grok:       { label: 'Grok',      description: 'Photorealistic supernova explosion' },
  remotion:   { label: 'Remotion',  description: 'DNA double helix rotating with labeled base pairs' },
};

export default function App() {
  const {
    segments,
    job,
    isLoading,
    error,
    generateFromPrompt,
    updateSegment,
    deleteSegment,
    moveSegment,
    startGeneration,
    pauseGeneration,
    startPolling,
    resetJob,
    setError,
  } = useSegments();

  const [selectedSegment, setSelectedSegment] = useState<Segment | null>(null);
  const [previewVideoUrl, setPreviewVideoUrl] = useState<string | null>(null);
  const [retryingSegmentId, setRetryingSegmentId] = useState<string | null>(null);
  const [viewingCodeSegmentId, setViewingCodeSegmentId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarTab, setSidebarTab] = useState<'segment' | 'voice' | 'history'>('segment');
  const [showVoiceover, setShowVoiceover] = useState(false);
  const [showVoiceSettings, setShowVoiceSettings] = useState(false);

  // Segment tester state
  const [segmentTypeDefaults, setSegmentTypeDefaults] = useState(FALLBACK_DEFAULTS);
  const [testSegType, setTestSegType] = useState('pysim');
  const [testSegDesc, setTestSegDesc] = useState(FALLBACK_DEFAULTS.pysim.description);
  const [testSegVoiceover, setTestSegVoiceover] = useState('');
  const [testSegDuration, setTestSegDuration] = useState(8);
  const [isTestingSegment, setIsTestingSegment] = useState(false);
  const [testJobId, setTestJobId] = useState<string | null>(null);
  const [testSegmentId, setTestSegmentId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ status: string; videoUrl?: string; code?: string; error?: string } | null>(null);
  const [testHistory, setTestHistory] = useState<GenerationJob[]>([]);
  const [expandedTestId, setExpandedTestId] = useState<string | null>(null);

  // TTS test state
  const [ttsText, setTtsText] = useState("Watch what happens. [pause] The signal just stops.");
  const [ttsSpeed, setTtsSpeed] = useState(1.0);
  const [ttsStability, setTtsStability] = useState(1.0);
  const [ttsSimilarity, setTtsSimilarity] = useState(1.0);
  const [ttsSeed, setTtsSeed] = useState('42');
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [ttsDuration, setTtsDuration] = useState<number | null>(null);

  const viewingCodeSegment = segments.find(s => s.id === viewingCodeSegmentId);

  const _refreshTestHistory = useCallback(() => {
    api.listJobs().then(res => {
      const tests = res.jobs
        .filter((j: GenerationJob) => j.segments.length === 1 && j.segments[0].title.startsWith('Test:'))
        .sort((a: GenerationJob, b: GenerationJob) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      setTestHistory(tests);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    api.getSegmentTypes().then(res => {
      const mapped: Record<string, { label: string; description: string }> = {};
      for (const [k, v] of Object.entries(res.types)) {
        mapped[k] = { label: (v as any).label, description: (v as any).description };
      }
      setSegmentTypeDefaults(mapped);
    }).catch(() => {});
    _refreshTestHistory();
  }, []);

  useEffect(() => {
    const d = segmentTypeDefaults[testSegType];
    if (d) setTestSegDesc(d.description);
  }, [testSegType, segmentTypeDefaults]);

  // Poll test segment status
  useEffect(() => {
    if (!testJobId || !testSegmentId) return;
    const interval = setInterval(async () => {
      try {
        const j = await api.getJob(testJobId);
        const seg = j.segments.find(s => s.id === testSegmentId);
        if (!seg) return;
        if (seg.status === 'completed') {
          setTestResult({ status: 'completed', videoUrl: api.getVideoUrl(testJobId, testSegmentId), code: seg.generated_script });
          setIsTestingSegment(false);
          _refreshTestHistory();
          clearInterval(interval);
        } else if (seg.status === 'failed') {
          setTestResult({ status: 'failed', error: seg.error || 'Unknown error' });
          setIsTestingSegment(false);
          _refreshTestHistory();
          clearInterval(interval);
        } else {
          setTestResult({ status: seg.status });
        }
      } catch {}
    }, 2000);
    return () => clearInterval(interval);
  }, [testJobId, testSegmentId]);

  const handleSegmentClick = (segment: Segment) => {
    if (segment.status === 'completed' && job) {
      setPreviewVideoUrl(api.getVideoUrl(job.id, segment.id));
    } else {
      setSelectedSegment(segment);
    }
  };

  const handleSegmentUpdate = (updates: Partial<Segment>) => {
    if (selectedSegment) updateSegment(selectedSegment.id, updates);
  };

  const handleRetrySegment = async (segmentId: string) => {
    if (!job) return;
    setRetryingSegmentId(segmentId);
    try { await api.retrySegment(job.id, segmentId); startPolling(); }
    catch (err) { console.error('Retry failed:', err); }
    finally { setRetryingSegmentId(null); }
  };

  const handleTTSTest = async () => {
    setIsTesting(true); setAudioUrl(null); setTtsDuration(null);
    try {
      const seed = ttsSeed.trim() ? parseInt(ttsSeed) : undefined;
      const result = await api.testTTS(ttsText, 'xKhbyU7E3bC6T89Kn26c', ttsSpeed, ttsStability, ttsSimilarity, seed);
      setAudioUrl(api.getAudioUrl(result.audio_url));
      setTtsDuration(result.duration);
    } catch (err) { setError(err instanceof Error ? err.message : 'TTS test failed'); }
    finally { setIsTesting(false); }
  };

  const handleTestSegment = async () => {
    setIsTestingSegment(true); setTestResult(null); setTestJobId(null); setTestSegmentId(null);
    try {
      const voiceover = testSegVoiceover.trim()
        ? { text: testSegVoiceover, voice: 'xKhbyU7E3bC6T89Kn26c', speed: 1.0 }
        : undefined;
      const result = await api.testSegment(testSegType, testSegDesc, voiceover, testSegDuration);
      setTestJobId(result.job_id);
      setTestSegmentId(result.segment_id);
    } catch (err) {
      setIsTestingSegment(false);
      setTestResult({ status: 'failed', error: err instanceof Error ? err.message : 'Failed to start test' });
    }
  };

  const isGenerating = job?.status === 'running';
  const canStart = segments.length > 0 && !isGenerating && job?.status !== 'completed';

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: '#09090b' }}>

      {/* ── Header ── */}
      <header className="shrink-0 border-b z-10 flex items-center justify-between px-5 py-2.5"
        style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.07)' }}>

        <div className="flex items-center gap-3">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 rounded-md text-zinc-600 hover:text-zinc-300 hover:bg-white/5 transition-colors"
            title={sidebarOpen ? 'Hide tools' : 'Show tools'}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: 'var(--color-iris-500)' }}>
            <svg className="w-4 h-4 text-black" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
          </div>
          <div>
            <h1 className="text-sm font-medium text-zinc-100 leading-none">Iris Flow</h1>
            <p className="text-[9px] text-zinc-700 uppercase tracking-widest mt-0.5">Video Pipeline</p>
          </div>
        </div>

        {/* Header right — quick segment stats when job exists but no panel expanded */}
        {job && (
          <div className="flex items-center gap-3 text-xs text-zinc-600">
            <span>{segments.filter(s => s.status === 'completed').length}/{segments.length} segments done</span>
            {job.status === 'running' && (
              <span className="flex items-center gap-1.5 text-amber-400">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                Running
              </span>
            )}
          </div>
        )}
      </header>

      {/* ── Body ── */}
      <div className="flex-1 flex overflow-hidden">

        {/* ── Left sidebar (dev tools) ── */}
        {sidebarOpen && (
          <aside className="w-80 shrink-0 flex flex-col overflow-hidden border-r"
            style={{ background: 'rgba(255,255,255,0.015)', borderColor: 'rgba(255,255,255,0.07)' }}>

            {/* Tab bar */}
            <div className="sidebar-tabs shrink-0">
              {(['segment', 'voice', 'history'] as const).map(tab => (
                <button
                  key={tab}
                  onClick={() => setSidebarTab(tab)}
                  className={`sidebar-tab ${sidebarTab === tab ? 'active' : ''}`}
                >
                  {tab === 'segment' ? 'Segment' : tab === 'voice' ? 'Voice' : `History${testHistory.length ? ` (${testHistory.length})` : ''}`}
                </button>
              ))}
            </div>

            {/* ── SEGMENT TAB ── */}
            {sidebarTab === 'segment' && (
              <div className="flex-1 overflow-y-auto flex flex-col">
                <div className="p-4 space-y-3 flex-1">

                  {/* Type selector — dropdown */}
                  <div>
                    <label className="section-label block mb-1.5">Type</label>
                    <select
                      value={testSegType}
                      onChange={e => setTestSegType(e.target.value)}
                      className="input-field text-sm"
                      style={{ fontSize: '0.8125rem' }}
                    >
                      <optgroup label="Visual">
                        <option value="animation">Animation</option>
                        <option value="grok">Grok</option>
                        <option value="remotion">Remotion</option>
                      </optgroup>
                      <optgroup label="Math & Science">
                        <option value="manim">Manim</option>
                        <option value="pysim">PySim</option>
                        <option value="stats">Stats</option>
                      </optgroup>
                      <optgroup label="Simulation">
                        <option value="mesa">Mesa</option>
                        <option value="pymunk">Pymunk</option>
                        <option value="simpy">SimPy</option>
                      </optgroup>
                      <optgroup label="Data">
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
                    </select>
                  </div>

                  {/* Description */}
                  <div>
                    <label className="section-label block mb-1.5">Description</label>
                    <textarea
                      value={testSegDesc}
                      onChange={e => setTestSegDesc(e.target.value)}
                      className="input-field resize-none"
                      style={{ fontSize: '0.8125rem', lineHeight: '1.5' }}
                      rows={3}
                      placeholder="Describe what this segment should show..."
                    />
                  </div>

                  {/* Duration stepper */}
                  <div className="flex items-center justify-between">
                    <label className="section-label">Duration</label>
                    <div className="stepper">
                      <button type="button" onClick={() => setTestSegDuration(d => Math.max(3, d - 1))}>−</button>
                      <span>{testSegDuration}s</span>
                      <button type="button" onClick={() => setTestSegDuration(d => Math.min(60, d + 1))}>+</button>
                    </div>
                  </div>

                  {/* Voiceover toggle */}
                  <div>
                    <button
                      type="button"
                      onClick={() => setShowVoiceover(v => !v)}
                      className="flex items-center gap-2 text-xs transition-colors"
                      style={{ color: showVoiceover ? '#4FC3F7' : '#52525b' }}
                    >
                      <span className={`w-4 h-4 rounded border flex items-center justify-center transition-colors ${showVoiceover ? 'border-sky-400 bg-sky-400/20' : 'border-zinc-700'}`}>
                        {showVoiceover && (
                          <svg className="w-2.5 h-2.5 text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                      </span>
                      Include voiceover
                    </button>
                    {showVoiceover && (
                      <textarea
                        value={testSegVoiceover}
                        onChange={e => setTestSegVoiceover(e.target.value)}
                        className="input-field resize-none mt-2"
                        style={{ fontSize: '0.8125rem' }}
                        rows={2}
                        placeholder="Narration text... use ... for pauses"
                      />
                    )}
                  </div>

                  {/* Generate button */}
                  <button
                    onClick={handleTestSegment}
                    disabled={isTestingSegment || !testSegDesc.trim()}
                    className="btn-primary w-full justify-center py-2.5"
                    style={{ fontSize: '0.8125rem' }}
                  >
                    {isTestingSegment ? (
                      <>
                        <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        Generating...
                      </>
                    ) : 'Generate segment'}
                  </button>

                  {/* Result */}
                  {testResult && (
                    <div style={{ animation: 'slide-up 0.15s ease' }}>
                      {testResult.status === 'processing' && (
                        <div className="flex items-center gap-2 py-2 text-xs text-amber-400">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
                          Processing segment...
                        </div>
                      )}
                      {testResult.status === 'completed' && testResult.videoUrl && (
                        <div className="rounded-lg overflow-hidden" style={{ border: '1px solid rgba(16,185,129,0.2)' }}>
                          <video src={testResult.videoUrl} controls className="w-full" style={{ maxHeight: 200, display: 'block' }} />
                          <div className="px-2 py-1.5 flex items-center gap-1.5" style={{ background: 'rgba(16,185,129,0.06)' }}>
                            <svg className="w-3 h-3 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                            </svg>
                            <span className="text-[10px] text-emerald-400">Segment complete</span>
                          </div>
                        </div>
                      )}
                      {testResult.status === 'failed' && (
                        <div className="rounded-lg p-3 text-xs text-red-400" style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}>
                          {testResult.error}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ── VOICE TAB ── */}
            {sidebarTab === 'voice' && (
              <div className="flex-1 overflow-y-auto flex flex-col">
                <div className="p-4 space-y-3 flex-1">
                  <div>
                    <label className="section-label block mb-1.5">Script</label>
                    <textarea
                      value={ttsText}
                      onChange={e => setTtsText(e.target.value)}
                      className="input-field resize-none"
                      style={{ fontSize: '0.8125rem', lineHeight: '1.6' }}
                      rows={5}
                      placeholder={"Type narration text here.\nUse ... for a short pause.\nUse ... ... for a longer beat."}
                    />
                    <p className="mt-1 text-[10px] text-zinc-700">Use <code className="text-zinc-500">...</code> for pauses</p>
                  </div>

                  {/* Generate */}
                  <button
                    onClick={handleTTSTest}
                    disabled={isTesting || !ttsText.trim()}
                    className="btn-primary w-full justify-center py-2.5"
                    style={{ fontSize: '0.8125rem' }}
                  >
                    {isTesting ? (
                      <>
                        <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        Generating...
                      </>
                    ) : (
                      <>
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072M12 6v12m-3.536-9.536a5 5 0 000 7.072" />
                        </svg>
                        Generate audio
                      </>
                    )}
                  </button>

                  {/* Audio result */}
                  {audioUrl && (
                    <div className="rounded-lg overflow-hidden" style={{ border: '1px solid rgba(255,255,255,0.08)', animation: 'slide-up 0.15s ease' }}>
                      <audio controls className="w-full" src={audioUrl} style={{ display: 'block' }} />
                      <div className="px-3 py-2 flex items-center justify-between" style={{ background: 'rgba(255,255,255,0.02)' }}>
                        <span className="text-[10px] text-zinc-600">eleven_v3</span>
                        {ttsDuration && <span className="text-[10px] text-zinc-600">{ttsDuration.toFixed(2)}s</span>}
                      </div>
                    </div>
                  )}

                  {/* Settings (collapsible) */}
                  <div className="rounded-lg overflow-hidden" style={{ border: '1px solid rgba(255,255,255,0.07)' }}>
                    <button
                      onClick={() => setShowVoiceSettings(s => !s)}
                      className="w-full flex items-center justify-between px-3 py-2.5 text-xs transition-colors"
                      style={{ color: '#71717a', background: 'rgba(255,255,255,0.02)' }}
                    >
                      <span>Voice settings</span>
                      <svg className={`w-3.5 h-3.5 transition-transform duration-200 ${showVoiceSettings ? 'rotate-90' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </button>
                    {showVoiceSettings && (
                      <div className="px-3 pb-3 pt-1 space-y-3" style={{ animation: 'slide-up 0.15s ease' }}>
                        {[
                          { label: 'Speed', value: ttsSpeed, set: setTtsSpeed, min: 0.7, max: 1.3, step: 0.01, display: `${ttsSpeed.toFixed(2)}x` },
                          { label: 'Stability', value: ttsStability, set: setTtsStability, min: 0, max: 1, step: 0.01, display: ttsStability.toFixed(2) },
                          { label: 'Similarity', value: ttsSimilarity, set: setTtsSimilarity, min: 0, max: 1, step: 0.01, display: ttsSimilarity.toFixed(2) },
                        ].map(({ label, value, set, min, max, step, display }) => (
                          <div key={label}>
                            <div className="flex justify-between mb-1">
                              <span className="text-[10px] text-zinc-600">{label}</span>
                              <span className="text-[10px] text-zinc-500 font-mono">{display}</span>
                            </div>
                            <input
                              type="range" min={min} max={max} step={step} value={value}
                              onChange={e => set(parseFloat(e.target.value))}
                              className="slider"
                            />
                          </div>
                        ))}
                        <div>
                          <label className="text-[10px] text-zinc-600 block mb-1">Seed <span className="text-zinc-700">(optional, for reproducibility)</span></label>
                          <input
                            type="number" placeholder="e.g. 42"
                            value={ttsSeed} onChange={e => setTtsSeed(e.target.value)}
                            className="input-field"
                            style={{ fontSize: '0.8125rem' }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* ── HISTORY TAB ── */}
            {sidebarTab === 'history' && (
              <div className="flex-1 overflow-y-auto">
                {testHistory.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full text-center px-6 py-12">
                    <div className="w-10 h-10 rounded-xl mb-3 flex items-center justify-center" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}>
                      <svg className="w-5 h-5 text-zinc-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    </div>
                    <p className="text-xs text-zinc-700">No tests yet.</p>
                    <p className="text-[10px] text-zinc-800 mt-0.5">Generate a segment to see results here.</p>
                  </div>
                ) : (
                  <div className="p-3 space-y-1.5">
                    {testHistory.map(tj => {
                      const seg = tj.segments[0];
                      const isExpanded = expandedTestId === tj.id;
                      const statusColor = seg.status === 'completed' ? '#10b981' : seg.status === 'failed' ? '#ef4444' : '#f59e0b';
                      return (
                        <div key={tj.id} className="rounded-lg overflow-hidden" style={{ border: `1px solid rgba(255,255,255,0.07)` }}>
                          <button
                            onClick={() => setExpandedTestId(isExpanded ? null : tj.id)}
                            className="w-full text-left px-3 py-2.5 flex items-center gap-2.5 transition-colors"
                            style={{ background: isExpanded ? 'rgba(255,255,255,0.03)' : 'transparent' }}
                          >
                            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: statusColor }} />
                            <div className="flex-1 min-w-0">
                              <p className="text-xs text-zinc-300 truncate">{segmentTypeDefaults[seg.type]?.label || seg.type}</p>
                              <p className="text-[10px] text-zinc-600 truncate mt-0.5">{seg.description}</p>
                            </div>
                            <svg className={`w-3 h-3 text-zinc-700 shrink-0 transition-transform duration-200 ${isExpanded ? 'rotate-90' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                            </svg>
                          </button>
                          {isExpanded && (
                            <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', animation: 'slide-up 0.15s ease' }}>
                              {seg.status === 'completed' && (
                                <video src={api.getVideoUrl(tj.id, seg.id)} controls className="w-full" style={{ maxHeight: 220, display: 'block', background: '#000' }} />
                              )}
                              {seg.error && (
                                <p className="px-3 py-2 text-[10px] text-red-400">{seg.error}</p>
                              )}
                              {seg.duration_seconds && (
                                <p className="px-3 py-1.5 text-[10px] text-zinc-700">{seg.duration_seconds.toFixed(1)}s · {new Date(tj.created_at).toLocaleTimeString()}</p>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </aside>
        )}

        {/* ── Main content ── */}
        <main className="flex-1 flex flex-col overflow-y-auto">

          {/* Prompt input */}
          <div className="shrink-0 p-5 pb-3">
            <PromptInput onSubmit={generateFromPrompt} isLoading={isLoading} />
          </div>

          {/* Error */}
          {error && (
            <div className="shrink-0 mx-5 mb-3 px-3 py-2.5 rounded-lg flex items-center justify-between text-sm text-red-400"
              style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}>
              {error}
              <button onClick={() => setError(null)} className="text-red-500 hover:text-red-300 ml-3">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}

          {/* Canvas */}
          <div className="flex-1 mx-5 mb-5 rounded-xl overflow-hidden" style={{ minHeight: 420, border: '1px solid rgba(255,255,255,0.06)' }}>
            {segments.length > 0 ? (
              <Canvas
                segments={segments}
                onSegmentDelete={deleteSegment}
                onSegmentMove={moveSegment}
                onSegmentClick={handleSegmentClick}
                onSegmentRetry={handleRetrySegment}
                onViewCode={(id) => setViewingCodeSegmentId(id)}
                selectedSegmentId={selectedSegment?.id}
                retryingSegmentId={retryingSegmentId || undefined}
              />
            ) : (
              <div className="canvas-bg h-full flex items-center justify-center">
                <div className="text-center">
                  <div className="w-14 h-14 rounded-2xl mx-auto mb-4 flex items-center justify-center"
                    style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
                    <svg className="w-7 h-7 text-zinc-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  </div>
                  <p className="text-sm text-zinc-600">Enter a prompt to generate segments</p>
                  <p className="text-xs text-zinc-800 mt-1">They'll appear here as an editable flow</p>
                </div>
              </div>
            )}
          </div>

          {/* Segment summary bar */}
          {segments.length > 0 && (
            <div className="shrink-0 px-5 pb-4 flex items-center justify-between text-xs text-zinc-700">
              <span>{segments.length} segment{segments.length !== 1 ? 's' : ''}</span>
              <div className="flex items-center gap-4">
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  {segments.filter(s => s.status === 'completed').length} complete
                </span>
                {segments.filter(s => s.status === 'processing').length > 0 && (
                  <span className="flex items-center gap-1.5 text-amber-500">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                    {segments.filter(s => s.status === 'processing').length} active
                  </span>
                )}
                {segments.filter(s => s.status === 'failed').length > 0 && (
                  <span className="flex items-center gap-1.5 text-red-500">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                    {segments.filter(s => s.status === 'failed').length} failed
                  </span>
                )}
              </div>
            </div>
          )}
        </main>

        {/* ── Right job panel (when job exists) ── */}
        {job && (
          <JobPanel
            job={job}
            segments={segments}
            isGenerating={isGenerating}
            canStart={canStart}
            onPause={pauseGeneration}
            onStart={startGeneration}
            onRetrySegment={handleRetrySegment}
            onViewVideo={(segId) => setPreviewVideoUrl(api.getVideoUrl(job.id, segId))}
            onViewCode={(segId) => setViewingCodeSegmentId(segId)}
            onClearJob={resetJob}
            retryingSegmentId={retryingSegmentId || undefined}
          />
        )}
      </div>

      {/* ── Modals ── */}
      {selectedSegment && job && (
        <SegmentEditor
          segment={selectedSegment}
          jobId={job.id}
          onClose={() => setSelectedSegment(null)}
          onUpdate={handleSegmentUpdate}
        />
      )}
      {viewingCodeSegment?.generated_script && (
        <CodeModal
          title={viewingCodeSegment.title}
          code={viewingCodeSegment.generated_script}
          onClose={() => setViewingCodeSegmentId(null)}
        />
      )}
      {previewVideoUrl && (
        <VideoPreview videoUrl={previewVideoUrl} onClose={() => setPreviewVideoUrl(null)} />
      )}
    </div>
  );
}
