/**
 * TaskDetailPage — v1 原版实现直移（components/task/TaskDetailPage，mode='full'）。
 * 本文件仅为路由薄包装：v1 组件自包含全部查询/干预/审批/退回重跑逻辑，
 * 视觉走 v2 token（类名 bg-page/text-ink/border-line 与 v1 同名，自动适配预览稿配色）。
 */
import { useNavigate, useParams } from 'react-router-dom';
import { TaskDetailPage as V1TaskDetailPage } from '../components/task/TaskDetailPage';

export function TaskDetailPage() {
  const { taskId = '' } = useParams();
  const nav = useNavigate();
  return (
    // 高度链：v1 组件根是 flex-1 min-h-0，需要 flex 列父容器才能撑起内部滚动
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <V1TaskDetailPage
        key={taskId}
        taskId={taskId}
        mode="full"
        onBack={() => nav('/tasks')}
      />
    </div>
  );
}
