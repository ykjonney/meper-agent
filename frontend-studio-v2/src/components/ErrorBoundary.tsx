/**
 * ErrorBoundary — 渲染错误兜底（显示错误详情 + 重试，不再白屏）。
 */
import { Component, type ReactNode } from 'react';

interface State { error: Error | null }

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          gap: 12, padding: 40, fontFamily: 'var(--font-sans)', color: 'var(--color-ink)',
        }}>
          <div style={{ fontSize: 28 }}>⚠️</div>
          <div style={{ fontSize: 15, fontWeight: 700 }}>页面渲染出错</div>
          <pre style={{
            maxWidth: 640, maxHeight: 200, overflow: 'auto', fontSize: 11, color: 'var(--color-ink-dim)',
            background: 'var(--color-well)', borderRadius: 8, padding: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
          }}>
            {this.state.error.message}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              background: 'linear-gradient(135deg, var(--color-brand-grad-from), var(--color-brand-grad-to))',
              color: 'var(--color-on-brand)', border: 'none', borderRadius: 8, padding: '8px 20px',
              fontSize: 12.5, fontWeight: 700, cursor: 'pointer',
            }}
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
