interface VideoPreviewProps {
  videoUrl: string;
  onClose: () => void;
}

export function VideoPreview({ videoUrl, onClose }: VideoPreviewProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div 
        className="bg-surface-100 rounded-2xl overflow-hidden max-w-3xl w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b border-surface-300">
          <h3 className="font-semibold">Video Preview</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="bg-black">
          <video
            src={videoUrl}
            controls
            autoPlay
            className="w-full max-h-[70vh]"
          >
            Your browser does not support the video tag.
          </video>
        </div>
      </div>
    </div>
  );
}
