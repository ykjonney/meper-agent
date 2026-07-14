// agent-flow-widget/src/components/FloatingButton.tsx

import { useState, useEffect, useRef, useCallback } from 'preact/hooks';

const POSITION_KEY = 'agent-chat-button-position';

interface ButtonPosition {
  x: number;
  y: number;
}

interface FloatingButtonProps {
  onClick: () => void;
  position: 'bottom-right' | 'bottom-left';
}

function getDefaultPosition(side: 'bottom-right' | 'bottom-left'): ButtonPosition {
  return {
    x: side === 'bottom-right' ? window.innerWidth - 76 : 20,
    y: window.innerHeight - 76,
  };
}

function clampPosition(pos: ButtonPosition): ButtonPosition {
  return {
    x: Math.max(0, Math.min(pos.x, window.innerWidth - 56)),
    y: Math.max(0, Math.min(pos.y, window.innerHeight - 56)),
  };
}

export function FloatingButton({ onClick, position: side }: FloatingButtonProps) {
  const [pos, setPos] = useState<ButtonPosition | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const hasMoved = useRef(false);
  const startPos = useRef<ButtonPosition>({ x: 0, y: 0 });
  const startMouse = useRef({ x: 0, y: 0 });

  // 加载保存的位置
  useEffect(() => {
    const saved = localStorage.getItem(POSITION_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (typeof parsed.x === 'number' && typeof parsed.y === 'number') {
          setPos(clampPosition(parsed));
        }
      } catch { /* ignore */ }
    }
  }, []);

  const effectivePos = pos ?? getDefaultPosition(side);

  const handleMouseDown = useCallback((e: MouseEvent) => {
    e.preventDefault();
    hasMoved.current = false;
    startMouse.current = { x: e.clientX, y: e.clientY };
    startPos.current = effectivePos;

    const handleMouseMove = (e: MouseEvent) => {
      const dx = e.clientX - startMouse.current.x;
      const dy = e.clientY - startMouse.current.y;
      // 超过 5px 才算拖拽（区分点击）
      if (Math.abs(dx) > 5 || Math.abs(dy) > 5) {
        hasMoved.current = true;
        setIsDragging(true);
        const newPos = clampPosition({
          x: startPos.current.x + dx,
          y: startPos.current.y + dy,
        });
        setPos(newPos);
      }
    };

    const handleMouseUp = () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      setIsDragging(false);
      if (hasMoved.current && pos) {
        localStorage.setItem(POSITION_KEY, JSON.stringify(pos));
      }
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [effectivePos, pos]);

  const handleClick = useCallback(() => {
    // 拖拽过就不触发点击
    if (hasMoved.current) return;
    onClick();
  }, [onClick]);

  const style: preact.JSX.CSSProperties = {
    position: 'fixed',
    left: `${effectivePos.x}px`,
    top: `${effectivePos.y}px`,
    width: '56px',
    height: '56px',
    borderRadius: '50%',
    backgroundColor: '#4F46E5',
    color: 'white',
    border: 'none',
    cursor: isDragging ? 'grabbing' : 'grab',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
    zIndex: 999998,
    transition: isDragging ? 'none' : 'box-shadow 0.2s',
  };

  return (
    <button
      style={style}
      onClick={handleClick}
      onMouseDown={handleMouseDown as any}
      onMouseEnter={(e) => {
        if (!isDragging) e.currentTarget.style.boxShadow = '0 6px 16px rgba(0, 0, 0, 0.2)';
      }}
      onMouseLeave={(e) => {
        if (!isDragging) e.currentTarget.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.15)';
      }}
      aria-label="打开聊天"
    >
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    </button>
  );
}
