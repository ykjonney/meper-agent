import React, { useState } from 'react';
import { useAppState } from '../AppContext';
import { Flow, FlowNodeRef } from '../types';
import { useTheme } from '../ThemeContext';
import { useTranslation } from '../LocaleContext';
import {
  Workflow, Plus, Trash2, Play, Clock, Layers,
  HelpCircle, ArrowRight
} from 'lucide-react';
import {
  Table, Tag, Button, Input, Select, Space, Card,
  Steps, Timeline, Empty, Typography, Popconfirm, Badge, Tooltip
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined,
  CloseOutlined, SaveOutlined, PlayCircleOutlined,
  PlusCircleOutlined, ClockCircleOutlined
} from '@ant-design/icons';
import { ResizableModal } from './ResizableModal';

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;

export const FlowsPage: React.FC = () => {
  const {
    flows,
    presetNodes,
    agents,
    addFlow,
    updateFlow,
    deleteFlow,
    triggerFlow,
    showNotification,
    setActiveTab
  } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();

  const [editingFlow, setEditingFlow] = useState<Flow | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [expandedFlowId, setExpandedFlowId] = useState<string | null>(null);

  // Form State
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [nodes, setNodes] = useState<FlowNodeRef[]>([]);

  const startCreate = () => {
    if (presetNodes.length === 0) {
      showNotification('warning', t('flows.presetNodeRequired'));
      setActiveTab('nodes');
      return;
    }
    setName('');
    setDescription('');
    setNodes([{ nodeId: presetNodes[0].id }]);
    setIsCreating(true);
    setEditingFlow(null);
  };

  const startEdit = (flow: Flow) => {
    setEditingFlow(flow);
    setName(flow.name);
    setDescription(flow.description);
    setNodes([...flow.nodes]);
    setIsCreating(true);
  };

  const handleAddField = () => {
    if (presetNodes.length === 0) return;
    setNodes([...nodes, { nodeId: presetNodes[0].id }]);
  };

  const handleRemoveField = (index: number) => {
    if (nodes.length <= 1) {
      showNotification('warning', t('flows.minNodeWarning'));
      return;
    }
    setNodes(nodes.filter((_, i) => i !== index));
  };

  const handleStepNodeChange = (index: number, nodeId: string) => {
    const updated = [...nodes];
    updated[index] = { ...updated[index], nodeId };
    setNodes(updated);
  };

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      showNotification('error', t('flows.nameRequired'));
      return;
    }
    if (nodes.length === 0) {
      showNotification('error', t('flows.nodeRequired'));
      return;
    }

    if (editingFlow) {
      updateFlow({
        ...editingFlow,
        name,
        description,
        nodes
      });
    } else {
      addFlow({
        name,
        description,
        nodes
      });
    }

    closeDrawer();
  };

  const closeDrawer = () => {
    setIsCreating(false);
    setEditingFlow(null);
  };

  const handleTrigger = (id: string) => {
    triggerFlow(id);
    setTimeout(() => {
      setActiveTab('tasks');
    }, 400);
  };

  // Table columns
  const columns = [
    {
      title: t('flows.columnFlowName'),
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: Flow) => (
        <div>
          <div className="font-semibold">{text}</div>
          <Text type="secondary" className="text-xs font-mono">{record.id}</Text>
        </div>
      ),
    },
    {
      title: t('flows.columnDesc'),
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (text: string) => <Text className="text-xs">{text || t('flows.noDesc')}</Text>,
    },
    {
      title: t('flows.columnNodeChain'),
      key: 'nodes',
      width: 280,
      render: (_: unknown, record: Flow) => (
        <div className="flex flex-wrap items-center gap-1">
          {record.nodes.slice(0, 4).map((nodeRef, idx) => {
            const targetNode = presetNodes.find(pn => pn.id === nodeRef.nodeId);
            return (
              <React.Fragment key={idx}>
                <Tag color="blue" className="text-xs m-0">
                  {idx + 1}. {targetNode?.name || t('flows.unknownNode')}
                </Tag>
                {idx < Math.min(record.nodes.length, 4) - 1 && (
                  <ArrowRight className="h-3 w-3" style={{ color: isDark ? '#595959' : '#bfbfbf' }} />
                )}
              </React.Fragment>
            );
          })}
          {record.nodes.length > 4 && (
            <Tag className="text-xs m-0">+{record.nodes.length - 4} {t('flows.moreNodes')}</Tag>
          )}
        </div>
      ),
    },
    {
      title: t('flows.columnStatus'),
      key: 'status',
      width: 120,
      render: (_: unknown, record: Flow) => (
        <div className="flex flex-col gap-1">
          <Tag color="blue">{record.nodes.length} {t('flows.nodeCount').replace('{count}', '')}</Tag>
          {record.lastTriggeredAt && (
            <Text type="secondary" className="text-xs">
              <ClockCircleOutlined className="mr-1" />
              {record.lastTriggeredAt}
            </Text>
          )}
        </div>
      ),
    },
    {
      title: t('flows.columnActions'),
      key: 'actions',
      width: 220,
      render: (_: unknown, record: Flow) => (
        <Space size={4}>
          <Button
            type="primary"
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={() => handleTrigger(record.id)}
          >
            {t('flows.runBtn')}
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => startEdit(record)}
          >
            {t('flows.editBtn')}
          </Button>
          <Popconfirm
            title={t('flows.confirmDelete').replace('{name}', record.name)}
            onConfirm={() => deleteFlow(record.id)}
            okText={t('flows.okText')}
            cancelText={t('flows.cancelText')}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
          <Tooltip title={t('flows.viewNodeChain')}>
            <Button
              size="small"
              icon={<Layers className="h-3.5 w-3.5" />}
              onClick={() => setExpandedFlowId(expandedFlowId === record.id ? null : record.id)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  // Build steps items for the expanded flow detail
  const getFlowSteps = (flow: Flow) => {
    return flow.nodes.map((nodeRef, idx) => {
      const targetNode = presetNodes.find(pn => pn.id === nodeRef.nodeId);
      const boundAgent = agents.find(a => a.id === targetNode?.agentId);
      return {
        title: targetNode?.name || t('flows.unknownNode'),
        description: boundAgent ? `${t('flows.execLabel')}: ${boundAgent.name}` : undefined,
        status: 'wait' as const,
      };
    });
  };

  return (
    <div className="px-4 py-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {/* Flows list */}
        <div className={`transition-all duration-200 ${isCreating ? 'lg:col-span-2' : 'lg:col-span-3'}`}>
          <Card size="small">
            {/* Toolbar */}
            <div className="flex items-center justify-between mb-4">
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={startCreate}
              >
                {t('flows.createFlow')}
              </Button>
            </div>

            {flows.length === 0 ? (
              <Empty
                image={<Workflow className="h-10 w-10" style={{ color: isDark ? '#595959' : '#bfbfbf' }} />}
                description={
                  <div>
                    <Title level={5}>{t('flows.emptyTitle')}</Title>
                    <Text type="secondary">{t('flows.emptyDesc')}</Text>
                  </div>
                }
              >
                <Button type="primary" onClick={startCreate}>{t('flows.createNow')}</Button>
              </Empty>
            ) : (
              <Table
                dataSource={flows.map(f => ({ ...f, key: f.id }))}
                columns={columns}
                pagination={false}
                size="middle"
              />
            )}
          </Card>

          {/* Expanded flow detail with Steps/Timeline */}
          {(() => {
            const flow = flows.find(f => f.id === expandedFlowId);
            if (!flow) return null;
            return (
              <ResizableModal
                open={!!expandedFlowId}
                onCancel={() => setExpandedFlowId(null)}
                width={800}
                title={
                  <div className="flex items-center gap-2">
                    <Workflow className="h-4 w-4 text-blue-500" />
                    <span>{t('flows.flowDetailTitle')}: {flow.name}</span>
                    <Tag color="blue">{flow.nodes.length} {t('flows.nodeSortCount').replace('{count}', '')}</Tag>
                  </div>
                }
                footer={null}
                draggable
                resizable
              >
                {flow.description && (
                  <Paragraph type="secondary" className="text-xs mb-4">{flow.description}</Paragraph>
                )}

                {/* Steps visualization */}
                <Steps
                  size="small"
                  current={-1}
                  items={getFlowSteps(flow)}
                  className="mb-4"
                />

                {/* Timeline view */}
                <div className="mt-4 pt-4" style={{ borderTop: `1px solid ${isDark ? '#303030' : '#f0f0f0'}` }}>
                  <Text type="secondary" className="text-xs font-semibold block mb-3">
                    {t('flows.timelineView')}
                  </Text>
                  <Timeline
                    items={flow.nodes.map((nodeRef, idx) => {
                      const targetNode = presetNodes.find(pn => pn.id === nodeRef.nodeId);
                      const boundAgent = agents.find(a => a.id === targetNode?.agentId);
                      return {
                        color: 'blue',
                        children: (
                          <div>
                            <div className="font-semibold text-xs">
                              {t('flows.stepLabel').replace('{index}', String(idx + 1))}: {targetNode?.name || t('flows.unknownNode')}
                            </div>
                            {boundAgent && (
                              <Text type="secondary" className="text-xs">
                                {t('flows.execAgentLabel')}: {boundAgent.name}
                              </Text>
                            )}
                          </div>
                        ),
                      };
                    })}
                  />
                </div>

                {/* Creation and trigger info */}
                <div className="mt-4 pt-3 flex items-center gap-6 text-xs" style={{ borderTop: `1px solid ${isDark ? '#303030' : '#f0f0f0'}`, color: isDark ? '#737373' : '#8c8c8c' }}>
                  <span className="flex items-center gap-1">
                    <Clock className="h-3.5 w-3.5" />
                    {t('flows.createdAt')}: {flow.createdAt}
                  </span>
                  {flow.lastTriggeredAt && (
                    <span className="flex items-center gap-1 text-blue-500">
                      <Clock className="h-3.5 w-3.5" />
                      {t('flows.lastTriggered')}: {flow.lastTriggeredAt}
                    </span>
                  )}
                </div>
              </ResizableModal>
            );
          })()}
        </div>

        {/* Create / Edit Panel */}
        {isCreating && (
          <div className="lg:col-span-1">
            <Card
              title={
                <div className="flex items-center gap-2">
                  <Workflow className="h-4 w-4 text-blue-500" />
                  <span>{editingFlow ? t('flows.editTitle') : t('flows.createTitle')}</span>
                </div>
              }
              extra={
                <Button type="text" icon={<CloseOutlined />} onClick={closeDrawer} />
              }
            >
              <form onSubmit={handleSave} className="flex flex-col gap-4">
                <div>
                  <label className="block text-xs font-semibold mb-1">
                    {t('flows.flowNameLabel')} <span className="text-red-500">*</span>
                  </label>
                  <Input
                    value={name}
                    onChange={e => setName(e.target.value)}
                    placeholder={t('flows.flowNamePlaceholder')}
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold mb-1">{t('flows.flowDescLabel')}</label>
                  <TextArea
                    rows={2}
                    value={description}
                    onChange={e => setDescription(e.target.value)}
                    placeholder={t('flows.flowDescPlaceholder')}
                  />
                </div>

                {/* Node selection stack */}
                <div className="pt-3" style={{ borderTop: `1px solid ${isDark ? '#303030' : '#f0f0f0'}` }}>
                  <div className="flex items-center justify-between mb-2.5">
                    <span className="font-bold text-xs flex items-center gap-1">
                      <Layers className="h-3.5 w-3.5 text-blue-500" />
                      {t('flows.stepConfigTitle')}
                    </span>
                    <Button
                      type="link"
                      size="small"
                      icon={<PlusCircleOutlined />}
                      onClick={handleAddField}
                    >
                      {t('flows.addStep')}
                    </Button>
                  </div>

                  <div className="flex flex-col gap-2 max-h-72 overflow-y-auto pr-1">
                    {nodes.map((nodeRef, idx) => (
                      <div
                        key={idx}
                        className="flex items-center gap-2 p-2 rounded border"
                        style={{
                          borderColor: isDark ? '#303030' : '#f0f0f0',
                          background: isDark ? '#1a1a1a' : '#fbfbfb'
                        }}
                      >
                        <span
                          className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full font-mono text-xs font-bold"
                          style={{
                            background: isDark ? '#303030' : '#f0f0f0',
                            color: isDark ? '#a6a6a6' : '#8c8c8c'
                          }}
                        >
                          {idx + 1}
                        </span>

                        <Select
                          value={nodeRef.nodeId}
                          onChange={v => handleStepNodeChange(idx, v)}
                          className="flex-1"
                          size="small"
                                                    options={presetNodes.map(pn => {
                            const agentObj = agents.find(a => a.id === pn.agentId);
                            return {
                              label: `${pn.name} (${agentObj?.name || t('flows.repoLabel')})`,
                              value: pn.id
                            };
                          })}
                        />

                        <Button
                          type="text"
                          size="small"
                          danger
                          icon={<Trash2 className="h-3.5 w-3.5" />}
                          onClick={() => handleRemoveField(idx)}
                        />
                      </div>
                    ))}
                  </div>
                </div>

                {/* Advisory notes */}
                <div
                  className="p-3 rounded flex items-start gap-1.5 text-xs"
                  style={{
                    background: isDark ? '#111d2c' : '#e6f4ff',
                    borderColor: isDark ? '#15325b' : '#91caee',
                    border: `1px solid ${isDark ? '#15325b' : 'rgba(145,202,238,0.2)'}`,
                    color: '#1677ff'
                  }}
                >
                  <HelpCircle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>
                    {t('flows.advisoryNote')}
                  </span>
                </div>

                <div className="flex items-center gap-2 mt-2 pt-4" style={{ borderTop: `1px solid ${isDark ? '#303030' : '#f0f0f0'}` }}>
                  <Button type="primary" htmlType="submit" icon={<SaveOutlined />} className="flex-1">
                    {t('flows.saveConfig')}
                  </Button>
                  <Button onClick={closeDrawer}>{t('flows.cancelText')}</Button>
                </div>
              </form>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
};
