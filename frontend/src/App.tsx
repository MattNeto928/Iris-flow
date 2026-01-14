import { useState } from 'react';
import { useSegments } from './hooks/useSegments';
import { PromptInput } from './components/PromptInput';
import { Canvas } from './components/Canvas';
import { SegmentEditor } from './components/SegmentEditor';
import { VideoPreview } from './components/VideoPreview';
import { CodeModal } from './components/CodeModal';
import type { Segment } from './types';
import { api } from './services/api';

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
    setError,
  } = useSegments();

  const [selectedSegment, setSelectedSegment] = useState<Segment | null>(null);
  const [previewVideoUrl, setPreviewVideoUrl] = useState<string | null>(null);
  const [retryingSegmentId, setRetryingSegmentId] = useState<string | null>(null);
  
  // TTS Testing state
  const [showTTSTest, setShowTTSTest] = useState(false);
  const [ttsText, setTtsText] = useState("Hello! This is a test of the Gemini text to speech system.");
  const [ttsVoice, setTtsVoice] = useState("Fenrir");
  const [ttsSpeed, setTtsSpeed] = useState(1.15);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [ttsDuration, setTtsDuration] = useState<number | null>(null);

  // Code view state - stored as ID to ensure updates from polling are reflected
  const [viewingCodeSegmentId, setViewingCodeSegmentId] = useState<string | null>(null);

  // Derived state
  const viewingCodeSegment = segments.find(s => s.id === viewingCodeSegmentId);

  const handleSegmentClick = (segment: Segment) => {
    // If completed, allow preview
    if (segment.status === 'completed' && job) {
      const choice = window.confirm('View video preview? (Cancel to edit instead)');
      if (choice) {
        setPreviewVideoUrl(api.getVideoUrl(job.id, segment.id));
        return;
      }
    }
    setSelectedSegment(segment);
  };

  const handleSegmentUpdate = (updates: Partial<Segment>) => {
    if (selectedSegment) {
      updateSegment(selectedSegment.id, updates);
    }
  };

  const handleTTSTest = async () => {
    setIsTesting(true);
    setAudioUrl(null);
    setTtsDuration(null);
    try {
      const result = await api.testTTS(ttsText, ttsVoice, ttsSpeed);
      setAudioUrl(api.getAudioUrl(result.audio_url));
      setTtsDuration(result.duration);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'TTS test failed');
    } finally {
      setIsTesting(false);
    }
  };

  const isGenerating = job?.status === 'running';
  const canStart = segments.length > 0 && !isGenerating && job?.status !== 'completed';

  const handleRetrySegment = async (segmentId: string) => {
    if (!job) return;
    
    setRetryingSegmentId(segmentId);
    try {
      // Fire-and-forget: backend now processes in background
      await api.retrySegment(job.id, segmentId);
      
      // Start polling to see live updates
      startPolling();
      
      // Clear retrying state - polling will show the actual processing status
      setRetryingSegmentId(null);
    } catch (err) {
      console.error('Retry failed:', err);
      setRetryingSegmentId(null);
    }
  };

  const handleViewCode = (segmentId: string) => {
    setViewingCodeSegmentId(segmentId);
  };

  return (
    <div className="h-full flex flex-col">
      <header className="flex-none bg-surface-100 border-b border-surface-200 bg-surface-100/80 backdrop-blur-sm z-10">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-iris-500 to-iris-700 flex items-center justify-center">
                <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </div>
              <div>
                <h1 className="text-xl font-bold text-white">Iris Flow</h1>
                <p className="text-xs text-gray-500">Video Generation Pipeline</p>
              </div>
            </div>

            {/* Job status */}
            {job && (
              <div className="flex items-center gap-4">
                <div className="text-sm">
                  <span className="text-gray-500">Status: </span>
                  <span className={`font-medium ${
                    job.status === 'running' ? 'text-yellow-500' :
                    job.status === 'completed' ? 'text-green-500' :
                    job.status === 'failed' ? 'text-red-500' :
                    'text-gray-400'
                  }`}>
                    {job.status.charAt(0).toUpperCase() + job.status.slice(1)}
                  </span>
                </div>
                
                {isGenerating ? (
                  <button onClick={pauseGeneration} className="btn-secondary">
                    Pause
                  </button>
                ) : (
                  canStart && (
                    <button onClick={startGeneration} className="btn-primary">
                      Start Generation
                    </button>
                  )
                )}

                {/* Download Full Video button - only shows when completed */}
                {job.status === 'completed' && (
                  <a 
                    href={api.getFinalVideoUrl(job.id)}
                    download
                    className="btn-primary flex items-center gap-2"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    Download Full Video
                  </a>
                )}
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden bg-[#0a0a0f] pattern-grid relative">
        {/* TTS Test Panel */}
        <div className="flex-shrink-0 max-w-4xl mx-auto w-full px-6 pt-4">
          <div className="glass-card p-4 mb-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-gray-300">🔊 TTS Audio Test</h3>
              <button
                onClick={() => setShowTTSTest(!showTTSTest)}
                className="text-xs text-iris-400 hover:text-iris-300"
              >
                {showTTSTest ? 'Hide' : 'Show'}
              </button>
            </div>
            
            {showTTSTest && (
              <div className="space-y-3">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Text to speak:</label>
                  <textarea
                    value={ttsText}
                    onChange={(e) => setTtsText(e.target.value)}
                    className="w-full bg-surface-200 border border-surface-300 rounded-lg p-2 text-sm text-white resize-none"
                    rows={2}
                  />
                </div>
                
                <div className="flex items-center gap-3">
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">Voice:</label>
                    <select
                      value={ttsVoice}
                      onChange={(e) => setTtsVoice(e.target.value)}
                      className="bg-surface-200 border border-surface-300 rounded-lg px-3 py-1.5 text-sm text-white"
                    >
                      <option value="Kore">Kore</option>
                      <option value="Schedar">Schedar</option>
                      <option value="Charon">Charon</option>
                      <option value="Fenrir">Fenrir</option>
                      <option value="Aoede">Aoede</option>
                      <option value="Puck">Puck</option>
                    </select>
                  </div>

                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">Speed: {ttsSpeed}x</label>
                    <input
                      type="range"
                      min="0.5"
                      max="2.0"
                      step="0.05"
                      value={ttsSpeed}
                      onChange={(e) => setTtsSpeed(parseFloat(e.target.value))}
                      className="w-24 h-2 bg-surface-300 rounded-lg appearance-none cursor-pointer"
                    />
                  </div>
                  
                  <button
                    onClick={handleTTSTest}
                    disabled={isTesting}
                    className="btn-primary mt-4"
                  >
                    {isTesting ? 'Generating...' : 'Generate Audio'}
                  </button>
                </div>
                
                {audioUrl && (
                  <div className="mt-4 p-3 bg-surface-200 rounded-lg">
                    <p className="text-xs text-gray-400 mb-2">
                      Duration: {ttsDuration?.toFixed(2)}s
                    </p>
                    <audio controls className="w-full" src={audioUrl}>
                      Your browser does not support the audio element.
                    </audio>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Prompt section */}
        <div className="flex-shrink-0 max-w-4xl mx-auto w-full px-6 py-6">
          <PromptInput onSubmit={generateFromPrompt} isLoading={isLoading} />
        </div>

        {/* Error display */}
        {error && (
          <div className="max-w-4xl mx-auto w-full px-6 mb-4">
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 flex items-center justify-between">
              <p className="text-red-400">{error}</p>
              <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
        )}

        {/* Canvas */}
        <div className="flex-1 overflow-hidden px-6 pb-6">
          <div className="h-full glass-card overflow-hidden relative">
            {segments.length > 0 ? (
              <Canvas
                segments={segments}
                jobStatus={job?.status || 'idle'}
                onSegmentDelete={deleteSegment}
                onSegmentMove={moveSegment}
                onSegmentClick={handleSegmentClick}
                onSegmentRetry={handleRetrySegment}
                onViewCode={handleViewCode}
                selectedSegmentId={selectedSegment?.id}
                retryingSegmentId={retryingSegmentId || undefined}
              />
            ) : (
                <div className="absolute inset-0 flex items-center justify-center text-gray-500">
                  <div className="text-center">
                    <div className="w-16 h-16 rounded-full bg-surface-200/50 mx-auto mb-4 flex items-center justify-center">
                      <svg className="w-8 h-8 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                      </svg>
                    </div>
                    <p>Start a new job to generate segments</p>
                  </div>
                </div>
            )}
          </div>
        </div>

        {/* Segment count indicator */}
        {segments.length > 0 && (
          <div className="flex-shrink-0 px-6 pb-4">
            <div className="flex items-center justify-between text-sm text-gray-500">
              <span>{segments.length} segment{segments.length !== 1 ? 's' : ''}</span>
              <div className="flex items-center gap-4">
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-status-completed" />
                  {segments.filter(s => s.status === 'completed').length} complete
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-status-processing animate-pulse" />
                  {segments.filter(s => s.status === 'processing').length} processing
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-status-failed" />
                  {segments.filter(s => s.status === 'failed').length} failed
                </span>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Segment editor modal */}
      {selectedSegment && job && (
        <SegmentEditor
          segment={selectedSegment}
          jobId={job.id}
          onClose={() => setSelectedSegment(null)}
          onUpdate={handleSegmentUpdate}
        />
      )}

      {/* Code viewer modal */}
      {viewingCodeSegment && viewingCodeSegment.generated_script && (
        <CodeModal
          title={viewingCodeSegment.title}
          code={viewingCodeSegment.generated_script}
          onClose={() => setViewingCodeSegmentId(null)}
        />
      )}

      {/* Video preview modal */}
      {previewVideoUrl && (
        <VideoPreview
          videoUrl={previewVideoUrl}
          onClose={() => setPreviewVideoUrl(null)}
        />
      )}
    </div>
  );
}
