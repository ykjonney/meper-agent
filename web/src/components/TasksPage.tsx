import React, { useState } from 'react';
import { useAppState } from '../AppContext';
import { Task, SubTask } from '../types';
import { useTheme } from '../ThemeContext';
import { useTranslation } from '../LocaleContext';
import {
  Plus, Search, CheckSquare, Layers, Clock, ArrowLeft, Play, Pause,
  Trash2, Eye, Calendar, User, Activity, AlertCircle, RefreshCw, ChevronRight, MessageSquare,
  Workflow, GitBranch, Zap, Bot
} from 'lucide-react';
import {
  Table, Tag, Button, Input, Select, Space, Card, Tabs, Progress,
  Modal, Badge, Tooltip, Empty, Typography, Dropdown, Popconfirm,
  Timeline, Descriptions
} from 'antd';
import {
  PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined,
  EyeOutlined, PlayCircleOutlined, PauseOutlined,
  CheckCircleOutlined, CloseOutlined, SendOutlined,
  ArrowLeftOutlined, AppstoreOutlined, UnorderedListOutlined,
  MessageOutlined
} from '@ant-design/icons';
import { ResizableModal } from './ResizableModal';

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;

export const TasksPage: React.FC = () => {
  const {
    tasks,
    agents,
    flows,
    presetNodes,
    addTask,
    updateTask,
    deleteTask,
    advanceTaskStatus,
    triggerFlow,
    setFocusedTaskId,
    focusedTaskId,
    editingTaskId,
    setEditingTaskId,
    setCurrentChatId,
    setActiveTab,
    showNotification
  } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();

  const [searchQuery, setSearchQuery] = useState('');
  const [priorityFilter, setPriorityFilter] = useState<string>('all');
  const [agentFilter, setAgentFilter] = useState<string>('all');
  const [viewMode, setViewMode] = useState<'kanban' | 'list'>('kanban');

  // New task form state
  const [formTitle, setFormTitle] = useState('');
  const [formDesc, setFormDesc] = useState('');
  const [formAgentId, setFormAgentId] = useState('');
  const [formFlowId, setFormFlowId] = useState<string>('');
  const [formPriority, setFormPriority] = useState<Task['priority']>('medium');
  const [formInputString, setFormInputString] = useState('{\n  "data_source": "s3://company-sales/2026/q1.csv",\n  "analysis_type": "trend"\n}');
  const [formMaxRetries, setFormMaxRetries] = useState(3);
  const [formTimeout, setFormTimeout] = useState(3600);

  // Filters
  const filteredTasks = tasks.filter(t => {
    const matchesSearch = t.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
                          t.description.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesPriority = priorityFilter === 'all' || t.priority === priorityFilter;
    const matchesAgent = agentFilter === 'all' || t.agentId === agentFilter;
    return matchesSearch && matchesPriority && matchesAgent;
  });

  const getPriorityColor = (p: Task['priority']): string => {
    switch (p) {
      case 'urgent': return 'red';
      case 'high': return 'orange';
      case 'medium': return 'gold';
      case 'low': return 'green';
    }
  };

  const getPriorityLabel = (p: Task['priority']): string => {
    const keys: Record<Task['priority'], string> = {
      urgent: 'priorityUrgent',
      high: 'priorityHigh',
      medium: 'priorityMedium',
      low: 'priorityLow',
    };
    return t(`tasks.${keys[p]}`);
  };

  const getStatusColor = (s: Task['status']): string => {
    switch (s) {
      case 'created': return 'default';
      case 'planned': return 'gold';
      case 'running': return 'blue';
      case 'paused': return 'orange';
      case 'review': return 'purple';
      case 'completed': return 'green';
      case 'failed': return 'red';
      case 'cancelled': return 'default';
      default: return 'default';
    }
  };

  const getStatusLabel = (s: Task['status']): string => {
    const keys: Record<Task['status'], string> = {
      created: 'created',
      planned: 'planned',
      running: 'running',
      paused: 'paused',
      review: 'review',
      completed: 'completed',
      failed: 'failed',
      cancelled: 'cancelled',
    };
    return t(`tasks.${keys[s]}`);
  };

  const handleOpenCreate = () => {
    const activeAg = agents.find(a => a.status === 'published');
    setFormTitle('全面 Q1 财务审计及预算异常溯源');
    setFormDesc('读取内部 S3 财务原始合并表单，过滤高精度分类数据，并对由于退款延迟引起的异常值进行模型聚类并输出为 SVG 可视化报告。');
    setFormAgentId(activeAg ? activeAg.id : '');
    setFormFlowId('');
    setFormPriority('medium');
    setFormInputString(JSON.stringify({
      data_source: "/workspace/finance_raw_sales.json",
      tolerance: 0.05,
      deep_trace_id: "tx-605"
    }, null, 2));
    setFormMaxRetries(3);
    setFormTimeout(3600);
    setEditingTaskId('new');
    setFocusedTaskId(null);
  };

  const handleCreateTaskSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (formFlowId) {
      try {
        const taskObj = triggerFlow(formFlowId);
        setEditingTaskId(null);
        setFocusedTaskId(taskObj.id);
        return;
      } catch (err: any) {
        showNotification('error', t('tasks.flowTriggerFailed').replace('{error}', err.message));
        return;
      }
    }

    if (!formTitle.trim() || !formAgentId) {
      showNotification('error', t('tasks.titleRequired'));
      return;
    }

    try {
      JSON.parse(formInputString);
    } catch {
      showNotification('error', t('tasks.jsonInvalid'));
      return;
    }

    const taskObj = addTask({
      title: formTitle,
      description: formDesc,
      status: 'created',
      priority: formPriority,
      agentId: formAgentId,
      subtasks: [],
      tags: [t('tasks.tagDynamic'), t('tasks.tagBusiness')],
      input: formInputString,
      maxRetries: formMaxRetries,
      timeout: formTimeout
    });

    setEditingTaskId(null);
    setFocusedTaskId(taskObj.id);
  };

  const focusTask = tasks.find(t => t.id === focusedTaskId);

  // Get status action items for a task
  const getStatusActions = (task: Task) => {
    const actions: Array<{ key: string; label: string; danger?: boolean }> = [];

    switch (task.status) {
      case 'created':
        actions.push({ key: 'planned', label: t('tasks.planStep') });
        break;
      case 'planned':
        actions.push({ key: 'running', label: t('tasks.startExec') });
        break;
      case 'running':
        actions.push({ key: 'paused', label: t('tasks.pauseSuspend') });
        break;
      case 'paused':
        actions.push({ key: 'running', label: t('tasks.resumeRestart') });
        break;
      case 'review':
        actions.push({ key: 'completed', label: t('tasks.approveComplete') });
        break;
    }

    if (task.status !== 'completed' && task.status !== 'cancelled') {
      actions.push({ key: 'cancelled', label: t('tasks.forceTerminate'), danger: true });
    }

    return actions;
  };

  const handleStatusAction = (taskId: string, action: string) => {
    advanceTaskStatus(taskId, action as Task['status']);
  };

  // Kanban columns
  const kanbanColumns: { id: Task['status']; name: string; color: string }[] = [
    { id: 'created', name: t('tasks.created'), color: '#8c8c8c' },
    { id: 'planned', name: t('tasks.planned'), color: '#faad14' },
    { id: 'running', name: t('tasks.running'), color: '#1677ff' },
    { id: 'review', name: t('tasks.review'), color: '#722ed1' },
    { id: 'completed', name: t('tasks.completed'), color: '#52c41a' }
  ];

  // Table columns for list view
  const listColumns = [
    {
      title: t('tasks.columnPriority'),
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
      render: (p: Task['priority']) => (
        <Tag color={getPriorityColor(p)}>{getPriorityLabel(p)}</Tag>
      ),
    },
    {
      title: t('tasks.columnTitle'),
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (text: string) => <span className="font-semibold text-sm">{text}</span>,
    },
    {
      title: t('tasks.columnAgent'),
      dataIndex: 'agentId',
      key: 'agentId',
      width: 160,
      render: (agentIdStr: string) => {
        const ag = agents.find(a => a.id === agentIdStr);
        return (
          <span className="flex items-center gap-1.5 text-xs">
            <Bot className="h-3.5 w-3.5" style={{ color: isDark ? '#a6a6a6' : '#595959' }} />
            {ag?.name || t('tasks.unknownAgent')}
          </span>
        );
      },
    },
    {
      title: t('tasks.columnStatus'),
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s: Task['status']) => (
        <Tag color={getStatusColor(s)}>{getStatusLabel(s)}</Tag>
      ),
    },
    {
      title: t('tasks.columnProgress'),
      dataIndex: 'progress',
      key: 'progress',
      width: 160,
      render: (progress: number, record: Task) => (
        <Progress
          percent={progress}
          size="small"
          status={record.status === 'completed' ? 'success' : 'active'}
          format={p => `${p}%`}
        />
      ),
    },
    {
      title: t('tasks.columnCreatedAt'),
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 120,
      render: (text: string) => <Text type="secondary" className="text-xs">{text.split(' ')[0]}</Text>,
    },
    {
      title: t('tasks.columnActions'),
      key: 'actions',
      width: 120,
      render: (_: unknown, record: Task) => (
        <Space size={4}>
          <Tooltip title={t('tasks.detailTitle')}>
            <Button
              size="small"
              icon={<EyeOutlined />}
              onClick={() => setFocusedTaskId(record.id)}
            />
          </Tooltip>
          {getStatusActions(record).length > 0 && (
            <Dropdown
              menu={{
                items: getStatusActions(record),
                onClick: ({ key }) => handleStatusAction(record.id, key),
              }}
            >
              <Button size="small" icon={<Activity className="h-3.5 w-3.5" />} />
            </Dropdown>
          )}
          <Popconfirm
            title={t('tasks.confirmTerminate')}
            onConfirm={() => deleteTask(record.id)}
            okText={t('tasks.okText')}
            cancelText={t('tasks.cancelText')}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className="px-4 py-6 flex flex-col h-full">

      {/* CREATE TASK VIEW */}
      {editingTaskId ? (
        <Card
          className="max-w-2xl mx-auto"
          title={
            <div className="flex items-center gap-2">
              <Plus className="h-4 w-4 text-blue-500" />
              <span>{t('tasks.createTaskTitle')}</span>
            </div>
          }
          extra={
            <Button
              type="link"
              icon={<ArrowLeftOutlined />}
              onClick={() => setEditingTaskId(null)}
            >
              {t('tasks.backToBoard')}
            </Button>
          }
        >
          <form onSubmit={handleCreateTaskSubmit} className="space-y-4">

            <div>
              <label className="block text-xs font-semibold mb-1">{t('tasks.taskTitleLabel')} <span className="text-red-500">*</span></label>
              <Input
                required
                value={formTitle}
                onChange={e => setFormTitle(e.target.value)}
                placeholder={t('tasks.taskTitlePlaceholder')}
              />
            </div>

            <div>
              <label className="block text-xs font-semibold mb-1">{t('tasks.taskDescLabel')}</label>
              <TextArea
                value={formDesc}
                onChange={e => setFormDesc(e.target.value)}
                placeholder={t('tasks.taskDescPlaceholder')}
                rows={2}
              />
            </div>

            {/* Flow selector */}
            <Card
              size="small"
              className="border-blue-200"
              style={{
                background: isDark ? '#111d2c' : undefined,
                borderColor: isDark ? '#15325b' : '#91caee'
              }}
              title={
                <span className="flex items-center gap-1.5 text-blue-600">
                  <GitBranch className="h-3.5 w-3.5" />
                  {t('tasks.flowRelateLabel')}
                  <Text type="secondary" className="text-xs font-normal">{t('tasks.flowRelateOptional')}</Text>
                </span>
              }
              extra={formFlowId ? (
                <Tag color="green" icon={<Zap className="h-3 w-3 inline-block mr-1" style={{ verticalAlign: -2 }} />}>
                  {t('tasks.flowModeActive')}
                </Tag>
              ) : null}
            >
              <Select
                value={formFlowId || undefined}
                onChange={v => setFormFlowId(v || '')}
                className="w-full"
                                allowClear
                placeholder={t('tasks.flowSelectPlaceholder')}
                options={flows.map(f => ({
                  label: `${f.name} (${f.nodes.length} ${t('tasks.flowStepCount').replace('{count}', '')})`,
                  value: f.id
                }))}
              />

              {/* Flow steps preview */}
              {formFlowId && (() => {
                const selectedFlow = flows.find(f => f.id === formFlowId);
                if (!selectedFlow) return null;
                return (
                  <div className="mt-3 p-3 rounded border" style={{
                    background: isDark ? '#0d1117' : '#fafafa',
                    borderColor: isDark ? '#303030' : '#f0f0f0'
                  }}>
                    <div className="text-xs mb-2" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>{selectedFlow.description}</div>
                    <div className="flex items-center gap-1 overflow-x-auto pb-1">
                      {selectedFlow.nodes.map((nodeRef, idx) => {
                        const preset = presetNodes.find(pn => pn.id === nodeRef.nodeId);
                        const isLast = idx === selectedFlow.nodes.length - 1;
                        return (
                          <div key={idx} className="flex items-center shrink-0">
                            <Tag color="blue" className="m-0">
                              {idx + 1}. {preset?.name || t('tasks.unknownAgent')}
                            </Tag>
                            {!isLast && (
                              <ChevronRight className="h-3.5 w-3.5 mx-0.5 shrink-0" style={{ color: isDark ? '#595959' : '#bfbfbf' }} />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })()}
            </Card>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold mb-1">{t('tasks.agentSelectLabel')} <span className="text-red-500">*</span></label>
                <Select
                  value={formAgentId || undefined}
                  onChange={v => setFormAgentId(v)}
                  className="w-full"
                                    placeholder={t('tasks.agentSelectPlaceholder')}
                  options={[
                    ...agents.filter(a => a.status === 'published').map(a => ({
                      label: `${a.name} (${t('tasks.agentPublished')}, ${a.skills.length} ${t('tasks.agentSkills')})`,
                      value: a.id
                    })),
                    ...agents.filter(a => a.status === 'draft').map(a => ({
                      label: `${a.name} (${t('tasks.agentDraft')}, ${t('tasks.agentNotSelectable')})`,
                      value: a.id,
                      disabled: true
                    })),
                  ]}
                />
              </div>

              <div>
                <label className="block text-xs font-semibold mb-1">{t('tasks.priorityLabel')}</label>
                <div className="flex gap-2">
                  {(['low', 'medium', 'high', 'urgent'] as const).map(pr => (
                    <Tag
                      key={pr}
                      color={formPriority === pr ? getPriorityColor(pr) : undefined}
                      className="cursor-pointer text-xs px-3 py-1 select-none"
                      onClick={() => setFormPriority(pr)}
                      style={formPriority !== pr ? {
                        borderColor: isDark ? '#303030' : '#d9d9d9',
                        color: isDark ? '#a6a6a6' : '#595959'
                      } : undefined}
                    >
                      {getPriorityLabel(pr)}
                    </Tag>
                  ))}
                </div>
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold mb-1">{t('tasks.inputJsonLabel')}</label>
              <TextArea
                value={formInputString}
                onChange={e => setFormInputString(e.target.value)}
                rows={4}
                className="font-mono text-xs"
                style={{ background: isDark ? '#141414' : '#1e1e1e', color: '#d4d4d4' }}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4 rounded-lg" style={{ background: isDark ? '#1a1a1a' : '#fafafa' }}>
              <div>
                <label className="block text-xs font-semibold mb-1">{t('tasks.maxRetriesLabel')}</label>
                <Input
                  type="number"
                  value={formMaxRetries}
                  onChange={e => setFormMaxRetries(Number(e.target.value))}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">{t('tasks.timeoutLabel')}</label>
                <Input
                  type="number"
                  value={formTimeout}
                  onChange={e => setFormTimeout(Number(e.target.value))}
                />
              </div>
            </div>

            <div className="flex gap-2 justify-end pt-4" style={{ borderTop: `1px solid ${isDark ? '#303030' : '#f0f0f0'}` }}>
              <Button onClick={() => setEditingTaskId(null)}>{t('tasks.cancelText')}</Button>
              <Button
                type="primary"
                htmlType="submit"
                icon={formFlowId ? <Zap className="h-3.5 w-3.5" /> : <PlusOutlined />}
              >
                {formFlowId ? t('tasks.createViaFlow') : t('tasks.createTask')}
              </Button>
            </div>

          </form>
        </Card>
      ) : (
        <div className="flex-1 flex flex-col min-h-0 gap-6 overflow-hidden">
          <Card size="small" className="flex-1 flex flex-col min-h-0">
            {/* Toolbar */}
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <div className="flex flex-wrap items-center gap-3">
                <Input
                  prefix={<SearchOutlined />}
                  placeholder={t('tasks.searchPlaceholder')}
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  style={{ width: 180 }}
                  allowClear
                />

                <Select
                  value={priorityFilter}
                  onChange={setPriorityFilter}
                  style={{ width: 130 }}
                  options={[
                    { label: t('tasks.allPriority'), value: 'all' },
                    { label: t('tasks.priorityUrgent'), value: 'urgent' },
                    { label: t('tasks.priorityHigh'), value: 'high' },
                    { label: t('tasks.priorityMedium'), value: 'medium' },
                    { label: t('tasks.priorityLow'), value: 'low' },
                  ]}
                />

                <Select
                  value={agentFilter}
                  onChange={setAgentFilter}
                  style={{ width: 160 }}
                  options={[
                    { label: t('tasks.allAgents'), value: 'all' },
                    ...agents.map(ag => ({
                      label: ag.name,
                      value: ag.id
                    })),
                  ]}
                />

                {/* View toggle using Tabs-like segmented control */}
                <div className="flex rounded overflow-hidden p-0.5" style={{ background: isDark ? '#1a1a1a' : '#f0f0f0' }}>
                  <Button
                    type={viewMode === 'kanban' ? 'primary' : 'text'}
                    size="small"
                    icon={<AppstoreOutlined />}
                    onClick={() => setViewMode('kanban')}
                  >
                    {t('tasks.kanbanView')}
                  </Button>
                  <Button
                    type={viewMode === 'list' ? 'primary' : 'text'}
                    size="small"
                    icon={<UnorderedListOutlined />}
                    onClick={() => setViewMode('list')}
                  >
                    {t('tasks.listView')}
                  </Button>
                </div>
              </div>

              <Button
                id="btn-add-task"
                type="primary"
                icon={<PlusOutlined />}
                onClick={handleOpenCreate}
              >
                {t('tasks.createTaskBtn')}
              </Button>
            </div>

          {/* KANBAN VIEW */}
          {viewMode === 'kanban' ? (
            <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4 items-stretch select-none flex-1 min-h-0" id="kanban-workspace">
              {kanbanColumns.map(col => {
                const colTasks = filteredTasks.filter(t => t.status === col.id);

                return (
                  <div
                    key={col.id}
                    className="rounded-lg border p-3 flex flex-col gap-3 h-full overflow-hidden"
                    style={{
                      borderColor: isDark ? '#303030' : '#f0f0f0',
                      borderTop: `2px solid ${col.color}`,
                      background: isDark ? '#141414' : '#fafafa'
                    }}
                  >
                    <div className="flex items-center justify-between pb-2 mb-1 px-1 shrink-0" style={{ borderBottom: `1px solid ${isDark ? '#262626' : '#f0f0f0'}` }}>
                      <span className="font-bold text-xs">{col.name}</span>
                      <Badge
                        count={colTasks.length}
                        style={{ backgroundColor: col.color }}
                        overflowCount={99}
                      />
                    </div>

                    <div className="flex-1 flex flex-col gap-3 overflow-y-auto pr-0.5 min-h-0">
                      {colTasks.length === 0 ? (
                        <div className="text-center py-6">
                          <Text type="secondary" className="text-xs">{t('tasks.noTasks')}</Text>
                        </div>
                      ) : (
                        colTasks.map(task => {
                          const ag = agents.find(a => a.id === task.agentId);

                          return (<React.Fragment key={task.id}>
                            <Card
                              id={`task-kanban-${task.id}`}
                              size="small"
                              className="cursor-pointer"
                              style={{
                                borderColor: focusedTaskId === task.id ? '#1677ff' : undefined,
                                boxShadow: focusedTaskId === task.id ? '0 0 0 2px rgba(22,119,255,0.1)' : undefined
                              }}
                              onClick={() => setFocusedTaskId(focusedTaskId === task.id ? null : task.id)}
                            >
                              {/* Priority tag */}
                              <div className="flex justify-between items-center mb-2">
                                <Tag color={getPriorityColor(task.priority)} className="text-xs m-0">
                                  {getPriorityLabel(task.priority)}
                                </Tag>
                                <Text type="secondary" className="text-xs font-mono shrink-0">
                                  {task.id.slice(0, 8)}
                                </Text>
                              </div>

                              <div className="space-y-1 mb-2">
                                <div className="font-semibold text-xs line-clamp-1">{task.title}</div>
                                <Text type="secondary" className="text-xs line-clamp-2 block" style={{ fontSize: 10 }}>{task.description}</Text>
                              </div>

                              {/* Progress bar */}
                              <div className="mb-2">
                                <div className="flex justify-between text-xs mb-1" style={{ fontSize: 10 }}>
                                  <span style={{ color: isDark ? '#737373' : '#8c8c8c' }}>{t('tasks.pipelineProgress')}</span>
                                  <span className="font-bold">{task.progress}%</span>
                                </div>
                                <Progress
                                  percent={task.progress}
                                  size="small"
                                  showInfo={false}
                                  status={task.status === 'completed' ? 'success' : 'active'}
                                  strokeColor={task.status === 'completed' ? '#52c41a' : '#1677ff'}
                                />
                              </div>

                              {/* Agent and date */}
                              <div className="flex items-center justify-between pt-2" style={{ borderTop: isDark ? "1px solid #262626" : "1px solid #f0f0f0" }}>
                                <span className="flex items-center gap-1 text-xs">
                                  <Bot className="h-3 w-3" style={{ color: isDark ? '#a6a6a6' : '#595959' }} />
                                  {ag?.name || t('tasks.unknownAgent')}
                                </span>
                                <Text type="secondary" className="text-xs">{task.createdAt.split(' ')[0]}</Text>
                              </div>

                              {/* Status action button */}
                              <div className="mt-2" onClick={e => e.stopPropagation()}>
                                {task.status === 'created' && (
                                  <Button size="small" block onClick={() => advanceTaskStatus(task.id, 'planned')}>
                                    {t('tasks.planStep')}
                                  </Button>
                                )}
                                {task.status === 'planned' && (
                                  <Button type="primary" size="small" block icon={<PlayCircleOutlined />} onClick={() => advanceTaskStatus(task.id, 'running')}>
                                    {t('tasks.startExec')}
                                  </Button>
                                )}
                                {task.status === 'running' && (
                                  <Button size="small" block icon={<PauseOutlined />} onClick={() => advanceTaskStatus(task.id, 'paused')}>
                                    {t('tasks.pauseSuspend')}
                                  </Button>
                                )}
                                {task.status === 'paused' && (
                                  <Button type="primary" size="small" block icon={<PlayCircleOutlined />} onClick={() => advanceTaskStatus(task.id, 'running')}>
                                    {t('tasks.resumeRestart')}
                                  </Button>
                                )}
                                {task.status === 'review' && (
                                  <Button type="primary" size="small" block icon={<CheckCircleOutlined />} style={{ background: '#52c41a', borderColor: '#52c41a' }} onClick={() => advanceTaskStatus(task.id, 'completed')}>
                                    {t('tasks.approveComplete')}
                                  </Button>
                                )}
                                {task.status === 'completed' && (
                                  <Tag color="green" className="w-full text-center m-0">
                                    <CheckCircleOutlined className="mr-1" />{t('tasks.runCompleted')}
                                  </Tag>
                                )}
                              </div>
                            </Card>
                          </React.Fragment>
                          );
                        })
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            /* LIST VIEW TABLE */
            <Table
              dataSource={filteredTasks.map(t => ({ ...t, key: t.id }))}
              columns={listColumns}
              pagination={false}
              size="middle"
              onRow={(record) => ({
                onClick: () => setFocusedTaskId(record.id),
                style: { cursor: 'pointer' },
              })}
              rowClassName={(record) =>
                focusedTaskId === record.id ? 'ant-table-row-selected' : ''
              }
            />
          )}
          </Card>

          {/* TASK DETAIL MODAL */}
          <ResizableModal
            open={!!focusTask}
            onCancel={() => setFocusedTaskId(null)}
            title={
              <div className="flex items-center gap-2">
                <span>{t('tasks.detailTitle')}: {focusTask?.title}</span>
                {focusTask && (
                  <Tag color={getPriorityColor(focusTask.priority)}>{getPriorityLabel(focusTask.priority)}</Tag>
                )}
              </div>
            }
            width={900}
            footer={null}
            className="task-detail-modal"
            draggable
            resizable
          >
            {focusTask && (
              <div className="space-y-5">

                {/* Description + Action Buttons */}
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                  <Paragraph type="secondary" className="text-xs max-w-3xl mb-0">{focusTask.description}</Paragraph>
                  <div className="flex items-center gap-2 shrink-0">
                    {focusTask.status === 'running' ? (
                      <Button
                        icon={<PauseOutlined />}
                        onClick={() => advanceTaskStatus(focusTask.id, 'paused')}
                        danger
                      >
                        {t('tasks.pauseSuspendBtn')}
                      </Button>
                    ) : (
                      <Button
                        type="primary"
                        icon={<PlayCircleOutlined />}
                        onClick={() => advanceTaskStatus(focusTask.id, focusTask.status === 'planned' ? 'running' : 'planned')}
                        disabled={focusTask.status === 'completed' || focusTask.status === 'cancelled'}
                      >
                        {t('tasks.startExecBtn')}
                      </Button>
                    )}
                    <Popconfirm
                      title={t('tasks.confirmTerminate')}
                      onConfirm={() => advanceTaskStatus(focusTask.id, 'cancelled')}
                      okText={t('tasks.okText')}
                      cancelText={t('tasks.cancelText')}
                    >
                      <Button
                        danger
                        disabled={focusTask.status === 'completed' || focusTask.status === 'cancelled'}
                      >
                        {t('tasks.forceTerminateBtn')}
                      </Button>
                    </Popconfirm>
                  </div>
                </div>

                {/* Flow execution pipeline */}
                {focusTask.flowId && (
                  <Card
                    size="small"
                    className="border-blue-200"
                    style={{
                      background: isDark ? '#111d2c' : undefined,
                      borderColor: isDark ? '#15325b' : '#91caee'
                    }}
                    title={
                      <span className="flex items-center gap-1.5 text-blue-500">
                        <Workflow className="h-4 w-4" />
                        {t('tasks.pipelineTitle')} ({focusTask.subtasks.length} {t('tasks.pipelineStepCount').replace('{count}', '')})
                      </span>
                    }
                  >
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                      {focusTask.subtasks.map((sub, idx) => {
                        const isCurrent = (focusTask.currentStepIndex ?? 0) === idx;
                        const isCompleted = sub.status === 'completed';

                        return (
                          <Card
                            key={sub.id}
                            size="small"
                            className="text-xs"
                            style={{
                              background: isCurrent
                                ? (isDark ? '#111d2c' : '#e6f4ff')
                                : isCompleted
                                ? (isDark ? '#0d2818' : '#f6ffed')
                                : undefined,
                              borderColor: isCurrent ? '#1677ff' : isCompleted ? '#52c41a' : (isDark ? '#303030' : '#f0f0f0'),
                            }}
                          >
                            <div className="flex items-center justify-between gap-1 mb-1">
                              <Tag color={isCurrent ? 'blue' : isCompleted ? 'green' : 'default'} className="m-0">
                                {t('tasks.stepN').replace('{index}', String(idx + 1))}
                              </Tag>
                              <Text type="secondary" className="text-xs">
                                {isCompleted ? t('tasks.stepCompleted') : isCurrent ? t('tasks.stepRunning') : t('tasks.stepWaiting')}
                              </Text>
                            </div>

                            <div className={`font-bold text-xs truncate mb-2 ${isCurrent ? 'text-blue-500' : isCompleted ? 'text-green-500' : ''}`}>
                              {sub.title}
                            </div>

                            <Progress
                              percent={sub.progress}
                              size="small"
                              status={isCompleted ? 'success' : 'active'}
                              strokeColor={isCompleted ? '#52c41a' : '#1677ff'}
                            />
                          </Card>
                        );
                      })}
                    </div>
                  </Card>
                )}

                {/* Detail info grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

                  {/* Left column */}
                  <div className="space-y-4">
                    {/* Task info */}
                    <Card size="small">
                      <div className="flex items-center justify-between">
                        <div>
                          <Text type="secondary" className="text-xs font-mono">{t('tasks.uuidLabel')}: {focusTask.id}</Text>
                          <div className="text-xs mt-0.5" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>
                            {t('tasks.createdAt')}: {focusTask.createdAt} | {t('tasks.updatedAt')}: {focusTask.updatedAt}
                          </div>
                          <div className="text-xs font-bold mt-1 flex items-center gap-1">
                            <Bot className="h-3 w-3" />
                            {t('tasks.agentProxy')}: {agents.find(a => a.id === focusTask.agentId)?.name || t('tasks.unknownBot')}
                          </div>
                        </div>
                        <Progress
                          type="circle"
                          percent={focusTask.progress}
                          size={56}
                          format={p => (
                            <div className="text-center">
                              <div className="font-bold text-xs">{p}%</div>
                              <div style={{ fontSize: 8, color: isDark ? '#737373' : '#8c8c8c' }}>{t('tasks.progressLabel')}</div>
                            </div>
                          )}
                        />
                      </div>
                    </Card>

                    {/* Subtask checklist */}
                    <Card size="small" title={<span className="text-xs font-semibold">{t('tasks.checklistTitle')}</span>}>
                      {focusTask.subtasks.length === 0 ? (
                        <Empty
                          description={t('tasks.noChecklist')}
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                        />
                      ) : (
                        <div className="space-y-2 max-h-[160px] overflow-y-auto">
                          {focusTask.subtasks.map((sub) => (
                            <div
                              key={sub.id}
                              className="flex items-center justify-between p-2 rounded border"
                              style={{
                                background: isDark ? '#1a1a1a' : '#fafafa',
                                borderColor: isDark ? '#262626' : '#f0f0f0'
                              }}
                            >
                              <div className="flex items-center gap-2">
                                {sub.status === 'completed' && <CheckCircleOutlined style={{ color: '#52c41a' }} />}
                                {sub.status === 'running' && <Badge status="processing" />}
                                {sub.status === 'pending' && <Badge status="default" />}
                                <span className="text-xs font-medium">{sub.title}</span>
                              </div>
                              <Text type="secondary" className="text-xs">
                                {sub.status === 'completed' ? t('tasks.subtaskCompleted') : sub.status === 'running' ? `${t('tasks.subtaskRunning')}(${sub.progress}%)` : t('tasks.subtaskPending')}
                              </Text>
                            </div>
                          ))}
                        </div>
                      )}
                    </Card>

                    {/* Chat source link */}
                    {focusTask.sourceChatId && (
                      <Card size="small" className="border-blue-200" style={{ borderColor: isDark ? '#15325b' : undefined }}>
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="font-bold text-xs flex items-center gap-1">
                              <MessageOutlined className="mr-1" />
                              {t('tasks.chatSourceTitle')}
                            </div>
                            <div className="text-xs mt-0.5">
                              {t('tasks.chatSourceDesc').replace('{agent}', agents.find(a => a.id === focusTask.agentId)?.name || 'AI')}
                            </div>
                          </div>
                          <Button
                            type="primary"
                            size="small"
                            icon={<MessageOutlined />}
                            onClick={() => {
                              setCurrentChatId(focusTask.sourceChatId!);
                              setActiveTab('chat');
                            }}
                          >
                            {t('tasks.jumpToChat')}
                          </Button>
                        </div>
                      </Card>
                    )}
                  </div>

                  {/* Right column */}
                  <div className="space-y-4">
                    {/* Input JSON */}
                    <Card size="small" title={<span className="text-xs font-semibold">{t('tasks.jsonInputsTitle')}</span>}>
                      <pre
                        className="font-mono text-xs p-2.5 rounded overflow-x-auto max-h-[140px] leading-relaxed"
                        style={{ background: '#141414', color: '#d4d4d4' }}
                      >
                        {focusTask.input}
                      </pre>
                    </Card>

                    {/* Status Timeline */}
                    <Card size="small" title={<span className="text-xs font-semibold">{t('tasks.statusTimeline')}</span>}>
                      <Timeline
                        className="mt-2"
                        items={focusTask.timeline.map(item => ({
                          color: item.status === t('tasks.timelineCompleted') ? 'green' : item.status === t('tasks.timelinePlanned') ? 'gold' : 'blue',
                          children: (
                            <div>
                              <div className="text-xs font-mono" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>
                                [{item.time}] <span className="font-bold">[{item.status}]</span>
                              </div>
                              <div className="text-xs mt-0.5">{item.message}</div>
                            </div>
                          ),
                        }))}
                      />
                    </Card>
                  </div>
                </div>
              </div>
            )}
          </ResizableModal>

        </div>
      )}

    </div>
  );
};
