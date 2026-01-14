import { useState, useRef, useCallback } from 'react';
import type { Segment } from '../types';
import { SegmentNode } from './SegmentNode';

interface CanvasProps {
  segments: Segment[];
  onSegmentClick: (segment: Segment) => void;
  onSegmentDelete: (segmentId: string) => void;
  onSegmentMove: (segmentId: string, x: number, y: number) => void;
  onSegmentRetry?: (segmentId: string) => void;
  onViewCode?: (segmentId: string) => void;
  selectedSegmentId?: string;
  retryingSegmentId?: string;
}

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2;
const ZOOM_SENSITIVITY = 0.001;

export function Canvas({
  segments,
  onSegmentClick,
  onSegmentDelete,
  onSegmentMove,
  onSegmentRetry,
  onViewCode,
  selectedSegmentId,
  retryingSegmentId,
}: CanvasProps) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [hasDragged, setHasDragged] = useState(false);
  
  // Pan and zoom state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });

  // Handle zoom with scroll wheel
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    
    // Mouse position relative to canvas
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    
    // Calculate new zoom
    const delta = -e.deltaY * ZOOM_SENSITIVITY;
    const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom + delta * zoom));
    
    if (newZoom === zoom) return;
    
    // Adjust pan to zoom towards mouse position
    const zoomRatio = newZoom / zoom;
    const newPanX = mouseX - (mouseX - pan.x) * zoomRatio;
    const newPanY = mouseY - (mouseY - pan.y) * zoomRatio;
    
    setZoom(newZoom);
    setPan({ x: newPanX, y: newPanY });
  }, [zoom, pan]);

  const handleMouseDown = useCallback((e: React.MouseEvent, segmentId: string) => {
    if (e.button !== 0) return; // Only left click
    
    const segment = segments.find(s => s.id === segmentId);
    if (!segment?.position) return;
    
    setDragging(segmentId);
    setHasDragged(false); // Reset drag state
    setOffset({
      x: (e.clientX - pan.x) / zoom - segment.position.x,
      y: (e.clientY - pan.y) / zoom - segment.position.y,
    });
    
    e.preventDefault();
    e.stopPropagation();
  }, [segments, zoom, pan]);

  // Handle canvas pan start (clicking on empty space)
  const handleCanvasMouseDown = useCallback((e: React.MouseEvent) => {
    // Only pan on left click or middle click
    // Segments call stopPropagation, so if we reach here with left click, it's background
    if (e.button === 0 || e.button === 1) {
      e.preventDefault();
      setIsPanning(true);
      setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }
  }, [pan]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    // Handle panning
    if (isPanning) {
      setPan({
        x: e.clientX - panStart.x,
        y: e.clientY - panStart.y,
      });
      return;
    }
    
    // Handle segment dragging
    if (!dragging) return;
    
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    
    const x = (e.clientX - pan.x) / zoom - offset.x;
    const y = (e.clientY - pan.y) / zoom - offset.y;
    
    setHasDragged(true); // Mark as dragged when moving
    onSegmentMove(dragging, Math.max(0, x), Math.max(0, y));
  }, [dragging, offset, onSegmentMove, isPanning, panStart, zoom, pan]);

  const handleMouseUp = useCallback(() => {
    setDragging(null);
    setIsPanning(false);
  }, []);

  const handleSegmentClick = useCallback((segment: Segment) => {
    // Only trigger click if we didn't drag
    if (!hasDragged) {
      onSegmentClick(segment);
    }
    setHasDragged(false);
  }, [hasDragged, onSegmentClick]);

  // Reset view to default
  const resetView = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  // Sort segments by order for arrow drawing
  const sortedSegments = [...segments].sort((a, b) => a.order - b.order);

  return (
    <div
      ref={canvasRef}
      className="canvas-bg relative w-full h-full min-h-[600px] overflow-hidden"
      style={{ cursor: isPanning ? 'grabbing' : 'default' }}
      onWheel={handleWheel}
      onMouseDown={handleCanvasMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      {/* Zoom controls */}
      <div className="absolute top-3 right-3 z-50 flex items-center gap-2 bg-surface-200/90 backdrop-blur-sm rounded-lg px-3 py-1.5 text-sm">
        <span className="text-gray-400">{Math.round(zoom * 100)}%</span>
        <button
          onClick={resetView}
          className="text-iris-400 hover:text-iris-300 transition-colors"
          title="Reset view"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      </div>

      {/* Transformable content container */}
      <div
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          transformOrigin: '0 0',
          width: '4000px',
          height: '4000px',
        }}
      >
        {/* Flow arrows */}
        <svg className="absolute inset-0 pointer-events-none" style={{ width: '4000px', height: '4000px' }}>
          <defs>
            <marker
              id="arrowhead"
              markerWidth="10"
              markerHeight="7"
              refX="9"
              refY="3.5"
              orient="auto"
            >
              <polygon points="0 0, 10 3.5, 0 7" fill="rgb(167, 139, 250)" opacity="0.6" />
            </marker>
          </defs>
          
          {sortedSegments.map((segment, index) => {
            if (index === 0) return null;
            const prev = sortedSegments[index - 1];
            
            if (!segment.position || !prev.position) return null;
            
            const cardWidth = 280;
            const cardHeight = 140;
            
            // Start from right side of previous card
            const startX = prev.position.x + cardWidth;
            const startY = prev.position.y + cardHeight / 2;
            
            // End at left side of current card
            const endX = segment.position.x;
            const endY = segment.position.y + cardHeight / 2;
            
            // Create curved path with horizontal bezier
            const controlOffset = Math.min(80, Math.abs(endX - startX) / 2);
            const path = `M ${startX} ${startY} C ${startX + controlOffset} ${startY}, ${endX - controlOffset} ${endY}, ${endX - 10} ${endY}`;
            
            return (
              <path
                key={`arrow-${prev.id}-${segment.id}`}
                d={path}
                className="flow-arrow"
                markerEnd="url(#arrowhead)"
              />
            );
          })}
        </svg>

        {/* Segment nodes */}
        {segments.map((segment) => (
          <div
            key={segment.id}
            className={`absolute transition-shadow ${dragging === segment.id ? 'dragging z-50' : ''}`}
            style={{
              left: segment.position?.x || 0,
              top: segment.position?.y || 0,
              cursor: dragging === segment.id ? 'grabbing' : 'grab',
            }}
            onMouseDown={(e) => handleMouseDown(e, segment.id)}
          >
            <SegmentNode
              segment={segment}
              onClick={() => handleSegmentClick(segment)}
              onDelete={() => onSegmentDelete(segment.id)}
              onRetry={segment.status === 'failed' && onSegmentRetry ? () => onSegmentRetry(segment.id) : undefined}
              onViewCode={segment.generated_script && onViewCode ? () => onViewCode(segment.id) : undefined}
              isSelected={selectedSegmentId === segment.id}
              isRetrying={retryingSegmentId === segment.id}
            />
          </div>
        ))}

        {/* Empty state */}
        {segments.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center" style={{ width: '100vw', height: '100vh' }}>
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-surface-200 flex items-center justify-center">
                <svg className="w-8 h-8 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </div>
              <h3 className="text-lg font-medium text-gray-400 mb-2">No segments yet</h3>
              <p className="text-sm text-gray-500 max-w-xs">
                Enter a prompt above to generate video segments. They'll appear here as an editable flowchart.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
