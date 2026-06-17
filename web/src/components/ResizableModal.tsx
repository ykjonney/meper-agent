import React, { useState, useRef, useCallback, useMemo } from 'react';
import { Modal } from 'antd';
import type { ModalProps } from 'antd';
import DraggableOrigin from 'react-draggable';
import { Resizable } from 're-resizable';
import type {
  Enable,
  HandleStyles,
  ResizeCallback,
  ResizeStartCallback,
} from 're-resizable';

// react-draggable@4.6.0 的类型定义把 DraggableCore 的 defaultProps 误标为必填,
// 断言为宽松类型以兼容 TS 严格模式(运行时 props 行为不变)
const Draggable = DraggableOrigin as unknown as React.FC<{
  handle?: string;
  nodeRef?: React.RefObject<HTMLElement | null>;
  bounds?:
    | { left: number; top: number; right: number; bottom: number }
    | string
    | boolean;
  position?: { x: number; y: number };
  onStart?: (e: any, data: any) => void | boolean;
  onStop?: (e: any, data: any) => void;
  children: React.ReactNode;
}>;

export interface ResizableModalProps extends ModalProps {
  minWidth?: number;
  maxWidth?: number;
  minHeight?: number;
  maxHeight?: number;
  resizable?: boolean;
  draggable?: boolean;
  defaultHeight?: number;
}

const DRAG_HANDLE = 'resizable-modal-drag-handle';

const FULL_ENABLE: Enable = {
  top: true,
  right: true,
  bottom: true,
  left: true,
  topRight: true,
  bottomRight: true,
  bottomLeft: true,
  topLeft: true,
};

// 8 方向 resize 手柄:四角淡色可见提示 + 四边/hover 高亮
const buildHandleStyles = (): HandleStyles => {
  const edge: React.CSSProperties = {
    position: 'absolute',
    background: 'transparent',
    transition: 'background-color .15s',
    zIndex: 10,
  };
  const cornerColor = 'rgba(22, 119, 255, 0.25)';
  return {
    top: { ...edge, top: 0, left: 0, right: 0, height: 6, cursor: 'ns-resize' },
    bottom: { ...edge, bottom: 0, left: 0, right: 0, height: 6, cursor: 'ns-resize' },
    left: { ...edge, top: 0, left: 0, bottom: 0, width: 6, cursor: 'ew-resize' },
    right: { ...edge, top: 0, right: 0, bottom: 0, width: 6, cursor: 'ew-resize' },
    topLeft: { ...edge, top: 0, left: 0, width: 14, height: 14, cursor: 'nwse-resize', background: cornerColor },
    topRight: { ...edge, top: 0, right: 0, width: 14, height: 14, cursor: 'nesw-resize', background: cornerColor },
    bottomLeft: { ...edge, bottom: 0, left: 0, width: 14, height: 14, cursor: 'nesw-resize', background: cornerColor },
    bottomRight: { ...edge, bottom: 0, right: 0, width: 14, height: 14, cursor: 'nwse-resize', background: cornerColor },
  };
};

export const ResizableModal: React.FC<ResizableModalProps> = ({
  children,
  width = 600,
  minWidth = 400,
  maxWidth = Math.floor(window.innerWidth * 0.9),
  minHeight = 200,
  maxHeight = Math.floor(window.innerHeight * 0.9),
  resizable = true,
  draggable = true,
  defaultHeight,
  title,
  wrapClassName,
  styles,
  ...restProps
}) => {
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [bounds, setBounds] = useState({
    left: 0,
    top: 0,
    right: 0,
    bottom: 0,
  });
  // width 始终受控;height 首次为 'auto'(贴合内容),用户首次拖动边缘时锁定为实测像素
  const [size, setSize] = useState<{ width: number | string; height: number | string }>({
    width,
    height: defaultHeight ?? 'auto',
  });
  const dragRef = useRef<HTMLDivElement>(null);

  const handleStyles = useMemo(() => buildHandleStyles(), []);

  // 拖拽开始:基于弹窗当前在视口的位置算 bounds,保证拖不出视口
  const onStart = useCallback(() => {
    const node = dragRef.current;
    if (!node) return;
    const { left, top } = node.getBoundingClientRect();
    setBounds({
      left: -left,
      top: -top,
      right: window.innerWidth - left - node.offsetWidth,
      bottom: window.innerHeight - top - node.offsetHeight,
    });
  }, []);

  const onStop = useCallback((_e: any, data: any) => {
    setPosition({ x: data.x, y: data.y });
  }, []);

  // 首次 resize:把 height 由 'auto' 锁定为实测像素,从此完全受控
  const onResizeStart = useCallback<ResizeStartCallback>((_e, _dir, ref) => {
    setSize((prev) =>
      prev.height === 'auto' ? { ...prev, height: ref.offsetHeight } : prev,
    );
  }, []);

  const onResize = useCallback<ResizeCallback>((_e, _dir, ref) => {
    setSize({ width: ref.offsetWidth, height: ref.offsetHeight });
  }, []);

  const onResizeStop = useCallback<ResizeCallback>((_e, _dir, ref) => {
    setSize({ width: ref.offsetWidth, height: ref.offsetHeight });
    // 尺寸变化后,bounds 的 right/bottom 需重算
    const node = dragRef.current;
    if (node) {
      const { left, top } = node.getBoundingClientRect();
      setBounds({
        left: -left,
        top: -top,
        right: window.innerWidth - left - node.offsetWidth,
        bottom: window.innerHeight - top - node.offsetHeight,
      });
    }
  }, []);

  // modalRender:外层 Draggable(管位置) + 内层 Resizable(管尺寸),包裹原始 .ant-modal
  const modalRender: ModalProps['modalRender'] = (node) => {
    // 给 .ant-modal 起初的可用尺寸(re-resizable 会基于此布局)
    const resizableStyle: React.CSSProperties =
      size.height === 'auto'
        ? { width: size.width, maxWidth: '100%' }
        : { width: size.width, height: size.height, maxWidth: '100%' };

    const inner = (
      <Resizable
        as="div"
        className="draggable-resizable-modal"
        style={resizableStyle}
        size={size}
        minWidth={minWidth}
        maxWidth={maxWidth}
        minHeight={minHeight}
        maxHeight={maxHeight}
        bounds="window"
        enable={resizable ? FULL_ENABLE : false}
        handleStyles={handleStyles}
        onResizeStart={onResizeStart}
        onResize={onResize}
        onResizeStop={onResizeStop}
      >
        {node}
      </Resizable>
    );

    if (!draggable) return inner;

    return (
      <Draggable
        handle={`.${DRAG_HANDLE}`}
        nodeRef={dragRef}
        bounds={bounds}
        position={position}
        onStart={onStart}
        onStop={onStop}
      >
        {inner}
      </Draggable>
    );
  };

  // 标题外包一层作为拖拽手柄(react-draggable handle 选择器),彻底干掉旧的 disabled 抖动写法
  const dragHandleTitle = draggable ? (
    <div className={DRAG_HANDLE} style={{ cursor: 'move', userSelect: 'none' }}>
      {title}
    </div>
  ) : (
    title
  );

  return (
    <Modal
      {...restProps}
      width="auto"
      title={dragHandleTitle}
      wrapClassName={`resizable-modal ${wrapClassName || ''}`}
      modalRender={modalRender}
      styles={{
        container: { height: '100%', display: 'flex', flexDirection: 'column' },
        body: { flex: 1, minHeight: 0, overflow: 'auto' },
        ...styles,
      }}
    >
      {children}
    </Modal>
  );
};

export default ResizableModal;
