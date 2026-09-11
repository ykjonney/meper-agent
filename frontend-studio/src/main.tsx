import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import App from './App.tsx';
import {AuthInitializer} from './components/AuthInitializer';
import {toast} from './components/ui/toast';
import {getErrorMessage} from './lib/api-client';
import './index.css';
import '@xyflow/react/dist/style.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
    mutations: {
      // 全局兜底：所有 mutation 失败自动 toast，避免遗漏 onError 导致静默。
      onError: (err: unknown) => {
        toast.error(getErrorMessage(err));
      },
    },
  },
});

// 全局兜底：#root 是 app-shell（height:100% + overflow:hidden），永远不该被滚动。
// 但 overflow:hidden 只挡用户滚动不挡程序化滚动——正文里逃逸的 absolute 元素会把
// #root 撑出可滚动溢出，scrollIntoView 等 API 就能把整个页面顶起（下方留白）。
// 任何来源的 #root 滚动一律归零。
document.getElementById('root')?.addEventListener('scroll', function () {
  if (this.scrollTop !== 0) this.scrollTop = 0;
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthInitializer>
        <App />
      </AuthInitializer>
    </QueryClientProvider>
  </StrictMode>,
);

