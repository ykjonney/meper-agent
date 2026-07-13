// agent-flow-widget/src/widget.tsx

import { render } from 'preact';
import { useState } from 'preact/hooks';
import type { WidgetConfig } from './types';
import { FloatingButton } from './components/FloatingButton';
import { ChatWindow } from './components/ChatWindow';

interface WidgetProps {
  config: WidgetConfig;
}

function Widget({ config }: WidgetProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <FloatingButton
        onClick={() => setIsOpen(true)}
        position={config.position || 'bottom-right'}
      />
      {isOpen && (
        <ChatWindow
          title={config.title || 'AI 助手'}
          onClose={() => setIsOpen(false)}
        />
      )}
    </>
  );
}

export function mountWidget(config: WidgetConfig, container: HTMLElement): void {
  const shadow = container.attachShadow({ mode: 'open' });

  const style = document.createElement('style');
  style.textContent = `
    @keyframes slideUp {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }
    * {
      box-sizing: border-box;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    }
  `;
  shadow.appendChild(style);

  const mountPoint = document.createElement('div');
  shadow.appendChild(mountPoint);

  render(<Widget config={config} />, mountPoint);
}
