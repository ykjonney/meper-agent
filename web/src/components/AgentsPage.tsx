import React, { useState } from 'react';
import { useAppState, Tab } from '../AppContext';
import { Agent, Skill, MCPServer, Flow } from '../types';
import { useTheme } from '../ThemeContext';
import {
  Plus, Search, Bot, Folder, Archive, AlertTriangle, Play, Edit,
  Trash2, ArrowLeft, Check, Layers, ChevronRight, HelpCircle, Eye, Settings, Workflow
} from 'lucide-react';
import { useTranslation } from '../LocaleContext';
import {
  Table, Tag, Button, Input, Select, Space, Modal, Form, Card,
  Descriptions, Badge, Tooltip, Empty, Typography, Radio, Divider,
  Popconfirm, message
} from 'antd';
import {
  PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined,
  PlayCircleOutlined, ArrowLeftOutlined, RobotOutlined, SettingOutlined,
  CheckCircleOutlined, CloseCircleOutlined
} from '@ant-design/icons';
import { ResizableModal } from './ResizableModal';

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;

export const AgentsPage: React.FC = () => {
  const {
    agents,
    skills,
    mcpServers,
    flows,
    tasks,
    addAgent,
    updateAgent,
    deleteAgent,
    addChat,
    setActiveTab,
    focusedAgentId,
    setFocusedAgentId,
    editingAgentId,
    setEditingAgentId,
    setFocusedTaskId
  } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();

  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [tagFilter, setTagFilter] = useState<string>('all');

  // Form states for create/edit
  const [formName, setFormName] = useState('');
  const [formDesc, setFormDesc] = useState('');
  const [formStatus, setFormStatus] = useState<Agent['status']>('draft');
  const [formType, setFormType] = useState<Agent['type']>('conversational');
  const [formTags, setFormTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState('');

  const [formSystemPrompt, setFormSystemPrompt] = useState('');
  const [formRole, setFormRole] = useState('');
  const [formTone, setFormTone] = useState('');
  const [formWelcome, setFormWelcome] = useState('');
  const [formConstraints, setFormConstraints] = useState<string[]>([]);
  const [constraintInput, setConstraintInput] = useState('');
  const [formVisibility, setFormVisibility] = useState<Agent['visibility']>('org');
  const [formVersion, setFormVersion] = useState('1.0.0');

  // Selected Skills/Mcp/Flows bindings
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [selectedMcp, setSelectedMcp] = useState<string[]>([]);
  const [selectedFlows, setSelectedFlows] = useState<string[]>([]);

  // Collect all unique tags for filter
  const allTags = Array.from(new Set(agents.flatMap(a => a.tags)));

  // Filtered listing
  const filteredAgents = agents.filter(agent => {
    const matchesSearch = agent.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                          agent.description.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === 'all' || agent.status === statusFilter;
    const matchesType = typeFilter === 'all' || agent.type === typeFilter;
    const matchesTag = tagFilter === 'all' || agent.tags.includes(tagFilter);
    return matchesSearch && matchesStatus && matchesType && matchesTag;
  });

  const getStatusColor = (status: Agent['status']): string => {
    switch (status) {
      case 'published': return 'green';
      case 'draft': return 'gold';
      case 'deprecated': return 'red';
      case 'archived': return 'default';
      default: return 'default';
    }
  };

  const getStatusLabel = (status: Agent['status']) => {
    switch (status) {
      case 'published': return t('agents.published');
      case 'draft': return t('agents.draft');
      case 'deprecated': return t('agents.deprecated');
      case 'archived': return t('agents.archived');
      default: return status;
    }
  };

  const getTypeLabel = (type: Agent['type']) => {
    switch (type) {
      case 'conversational': return t('agents.conversational');
      case 'service': return t('agents.service');
      case 'hybrid': return t('agents.hybrid');
      default: return type;
    }
  };

  // Open creation mode
  const handleOpenCreate = () => {
    setFormName('');
    setFormDesc('');
    setFormStatus('draft');
    setFormType('conversational');
    setFormTags(['数据', '工具']);
    setFormSystemPrompt('你是一个专业的智能代理...');
    setFormRole('通用助手');
    setFormTone('严谨、温和、提供事实');
    setFormWelcome('你好！我是你的智能代理，随时听候调遣。');
    setFormConstraints(['提供客观中立的事实信息']);
    setFormVisibility('org');
    setFormVersion('1.0.0');
    setSelectedSkills([]);
    setSelectedMcp([]);
    setSelectedFlows([]);
    setEditingAgentId('new');
    setFocusedAgentId(null);
  };

  // Open edit mode preloading records
  const handleOpenEdit = (agent: Agent) => {
    setFormName(agent.name);
    setFormDesc(agent.description);
    setFormStatus(agent.status);
    setFormType(agent.type);
    setFormTags(agent.tags);
    setFormSystemPrompt(agent.systemPrompt);
    setFormRole(agent.persona.role);
    setFormTone(agent.persona.tone);
    setFormWelcome(agent.persona.welcomeMessage);
    setFormConstraints(agent.persona.constraints);
    setFormVisibility(agent.visibility);
    setFormVersion(agent.version);
    setSelectedSkills(agent.skills);
    setSelectedMcp(agent.mcpServers);
    setSelectedFlows(agent.flows || []);
    setEditingAgentId(agent.id);
    setFocusedAgentId(null);
  };

  const handleSaveAgent = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formName.trim()) return;

    const dataObj = {
      name: formName,
      description: formDesc,
      status: formStatus,
      type: formType,
      tags: formTags,
      systemPrompt: formSystemPrompt,
      persona: {
        role: formRole,
        tone: formTone,
        welcomeMessage: formWelcome,
        constraints: formConstraints
      },
      models: [
        { model: 'claude-3-5-sonnet', priority: 10, maxTokens: 8192, temperature: 0.5, enabled: true }
      ],
      skills: selectedSkills,
      mcpServers: selectedMcp,
      flows: selectedFlows,
      visibility: formVisibility,
      version: formVersion
    };

    if (editingAgentId === 'new') {
      const created = addAgent(dataObj);
      setEditingAgentId(null);
      setFocusedAgentId(created.id);
    } else if (editingAgentId) {
      updateAgent({
        ...dataObj,
        id: editingAgentId
      });
      setEditingAgentId(null);
      setFocusedAgentId(editingAgentId);
    }
  };

  const handleAddTag = () => {
    if (tagInput.trim() && !formTags.includes(tagInput.trim())) {
      setFormTags([...formTags, tagInput.trim()]);
      setTagInput('');
    }
  };

  const handleRemoveTag = (index: number) => {
    setFormTags(formTags.filter((_, i) => i !== index));
  };

  const handleAddConstraint = () => {
    if (constraintInput.trim() && !formConstraints.includes(constraintInput.trim())) {
      setFormConstraints([...formConstraints, constraintInput.trim()]);
      setConstraintInput('');
    }
  };

  const handleRemoveConstraint = (index: number) => {
    setFormConstraints(formConstraints.filter((_, i) => i !== index));
  };

  const handleToggleSkillSelection = (skillId: string) => {
    if (selectedSkills.includes(skillId)) {
      setSelectedSkills(selectedSkills.filter(id => id !== skillId));
    } else {
      setSelectedSkills([...selectedSkills, skillId]);
    }
  };

  const handleToggleMcpSelection = (mcpId: string) => {
    if (selectedMcp.includes(mcpId)) {
      setSelectedMcp(selectedMcp.filter(id => id !== mcpId));
    } else {
      setSelectedMcp([...selectedMcp, mcpId]);
    }
  };

  const handleToggleFlowSelection = (flowId: string) => {
    if (selectedFlows.includes(flowId)) {
      setSelectedFlows(selectedFlows.filter(id => id !== flowId));
    } else {
      setSelectedFlows([...selectedFlows, flowId]);
    }
  };

  // Find active focus agent
  const focusAgent = agents.find(a => a.id === focusedAgentId);

  // Recent tasks associated with active focus agent
  const focusRecentTasks = focusAgent ? tasks.filter(t => t.agentId === focusAgent.id).slice(0, 5) : [];

  // Cumulative aggregate tools
  const getAggregateTools = (agent: Agent) => {
    const list: Array<{ name: string; origin: string; type: 'skill' | 'mcp' }> = [];

    agent.skills.forEach(sId => {
      const sk = skills.find(s => s.id === sId);
      if (sk) {
        list.push({ name: sk.name, origin: 'Skill', type: 'skill' });
      }
    });

    agent.mcpServers.forEach(srvId => {
      const srv = mcpServers.find(s => s.id === srvId);
      if (srv) {
        srv.tools.forEach(t => {
          list.push({ name: t.name, origin: `${srv.name} (MCP)`, type: 'mcp' });
        });
      }
    });

    return list;
  };

  // Table columns definition
  const columns = [
    {
      title: t('agents.agentName'),
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: Agent) => (
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 border border-blue-100">
            <Bot className="h-4 w-4" />
          </div>
          <div>
            <div className="font-semibold text-sm">{text}</div>
            <Text type="secondary" className="text-xs">{getTypeLabel(record.type)}</Text>
          </div>
        </div>
      ),
    },
    {
      title: t('agents.descLabel'),
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (text: string) => <Text className="text-xs">{text}</Text>,
    },
    {
      title: t('agents.statusLabel'),
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: Agent['status']) => (
        <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
      ),
    },
    {
      title: t('agents.tagLabel'),
      dataIndex: 'tags',
      key: 'tags',
      width: 180,
      render: (tags: string[]) => (
        <Space size={[4, 4]} wrap>
          {tags.slice(0, 3).map((tag, i) => (
            <Tag key={i} className="text-xs">{tag}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: t('agents.bindings'),
      key: 'bindings',
      width: 120,
      render: (_: unknown, record: Agent) => (
        <Space size={8} className="text-xs">
          <Tooltip title="Skills">
            <Badge count={record.skills.length} size="small" color="blue">
              <Layers className="h-4 w-4" style={{ color: isDark ? '#a6a6a6' : '#595959' }} />
            </Badge>
          </Tooltip>
          <Tooltip title="MCP Servers">
            <Badge count={record.mcpServers.length} size="small" color="purple">
              <Settings className="h-4 w-4" style={{ color: isDark ? '#a6a6a6' : '#595959' }} />
            </Badge>
          </Tooltip>
        </Space>
      ),
    },
    {
      title: t('agents.versionLabel'),
      dataIndex: 'version',
      key: 'version',
      width: 80,
      render: (v: string) => <Text code className="text-xs">v{v}</Text>,
    },
    {
      title: t('agents.actionsLabel'),
      key: 'actions',
      width: 180,
      render: (_: unknown, record: Agent) => (
        <Space size={4}>
          {record.status === 'published' ? (
            <Button
              type="primary"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => addChat(record.id)}
            >
              {t('agents.chatBtn')}
            </Button>
          ) : (
            <Tag>{t('agents.draftBox')}</Tag>
          )}
          <Tooltip title={t('agents.viewDetail')}>
            <Button
              size="small"
              icon={<Eye className="h-3.5 w-3.5" />}
              onClick={() => setFocusedAgentId(record.id)}
            />
          </Tooltip>
          <Tooltip title={t('agents.editLabel')}>
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleOpenEdit(record)}
            />
          </Tooltip>
          <Popconfirm
            title={t('agents.confirmDelete').replace('{name}', record.name)}
            onConfirm={() => deleteAgent(record.id)}
            okText={t('common.confirm')}
            cancelText={t('common.cancel')}
          >
            <Tooltip title={t('agents.deleteLabel')}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className="px-4 py-6">

      {/* EDITING / CREATION VIEW */}
      {editingAgentId ? (
        <Card
          className="max-w-3xl mx-auto"
          title={
            <div className="flex items-center gap-2">
              {editingAgentId === 'new' ? (
                <>
                  <RobotOutlined className="text-blue-500" />
                  <span>{t('agents.createNew')}</span>
                </>
              ) : (
                <>
                  <EditOutlined className="text-blue-500" />
                  <span>{t('agents.editAgent')}: {formName}</span>
                </>
              )}
            </div>
          }
          extra={
            <Button
              type="link"
              icon={<ArrowLeftOutlined />}
              onClick={() => setEditingAgentId(null)}
            >
              {t('agents.backToList')}
            </Button>
          }
        >
          <form onSubmit={handleSaveAgent} className="space-y-6">

            {/* Sec 1: Basic info */}
            <Card type="inner" title={<span className="flex items-center gap-1.5"><Layers className="h-4 w-4 text-blue-500" /> 1. {t('agents.basicInfo')}</span>} size="small">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold mb-1">{t('agents.agentNameLabel')} <span className="text-red-500">*</span></label>
                  <Input
                    required
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="例如: 财务分析助手, WebScraper"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold mb-1">{t('agents.typeLabel')}</label>
                  <Radio.Group
                    value={formType}
                    onChange={(e) => setFormType(e.target.value)}
                    optionType="button"
                    buttonStyle="solid"
                    size="small"
                    options={[
                      { label: t('agents.conversational'), value: 'conversational' },
                      { label: t('agents.service'), value: 'service' },
                      { label: t('agents.hybrid'), value: 'hybrid' },
                    ]}
                  />
                </div>
              </div>

              <div className="mt-4">
                <label className="block text-xs font-semibold mb-1">{t('agents.descDetail')}</label>
                <TextArea
                  value={formDesc}
                  onChange={(e) => setFormDesc(e.target.value)}
                  placeholder={t('agents.descPlaceholder')}
                  rows={2}
                />
              </div>

              <div className="mt-4">
                <label className="block text-xs font-semibold mb-1">{t('agents.tagCategory')}</label>
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  {formTags.map((tag, i) => (
                    <Tag key={i} closable onClose={() => handleRemoveTag(i)} color="blue">{tag}</Tag>
                  ))}
                </div>
                <Space>
                  <Input
                    size="small"
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    placeholder={t('agents.addTagPlaceholder')}
                    style={{ width: 160 }}
                    onPressEnter={handleAddTag}
                  />
                  <Button size="small" onClick={handleAddTag}>{t('agents.addBtn')}</Button>
                </Space>
              </div>
            </Card>

            {/* Sec 2: Prompt configuration */}
            <Card type="inner" title={<span className="flex items-center gap-1.5"><Settings className="h-4 w-4 text-indigo-500" /> 2. {t('agents.systemPrompt')}</span>} size="small">
              <label className="block text-xs font-semibold mb-1">{t('agents.metaPromptLabel')}</label>
              <TextArea
                value={formSystemPrompt}
                onChange={(e) => setFormSystemPrompt(e.target.value)}
                rows={4}
                className="font-mono text-xs"
              />
              <Text type="secondary" className="text-xs mt-1 block">{t('agents.metaPromptHint')}</Text>
            </Card>

            {/* Sec 3: Persona */}
            <Card type="inner" title={<span className="flex items-center gap-1.5"><Bot className="h-4 w-4 text-emerald-500" /> 3. {t('agents.persona')}</span>} size="small">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold mb-1">{t('agents.roleLabel')}</label>
                  <Input
                    value={formRole}
                    onChange={(e) => setFormRole(e.target.value)}
                    placeholder="如: 高级商业顾问"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold mb-1">{t('agents.toneLabel')}</label>
                  <Input
                    value={formTone}
                    onChange={(e) => setFormTone(e.target.value)}
                    placeholder="如: 简明精巧、技术专业、中文"
                  />
                </div>
              </div>

              <div className="mt-4">
                <label className="block text-xs font-semibold mb-1">{t('agents.welcomeLabel')}</label>
                <TextArea
                  value={formWelcome}
                  onChange={(e) => setFormWelcome(e.target.value)}
                  rows={2}
                />
              </div>

              <div className="mt-4">
                <label className="block text-xs font-semibold mb-1">{t('agents.constraintLabel')}</label>
                <div className="space-y-1.5 mb-2">
                  {formConstraints.map((con, i) => (
                    <div key={i} className="flex items-center justify-between px-3 py-1 rounded text-xs" style={{ background: isDark ? '#262626' : '#fafafa' }}>
                      <span>{con}</span>
                      <Button type="text" size="small" danger onClick={() => handleRemoveConstraint(i)}>x</Button>
                    </div>
                  ))}
                </div>
                <Space>
                  <Input
                    size="small"
                    value={constraintInput}
                    onChange={(e) => setConstraintInput(e.target.value)}
                    placeholder={t('agents.constraintPlaceholder')}
                    style={{ width: 300 }}
                    onPressEnter={handleAddConstraint}
                  />
                  <Button size="small" onClick={handleAddConstraint}>{t('agents.addBtn')}</Button>
                </Space>
              </div>
            </Card>

            {/* Sec 4: Model Preferences */}
            <Card type="inner" title={<span className="flex items-center gap-1.5"><Settings className="h-4 w-4 text-amber-500" /> 4. {t('agents.modelPrefs')}</span>} size="small">
              <Table
                size="small"
                pagination={false}
                dataSource={[
                  { key: '1', model: 'claude-3-5-sonnet (默认)', priority: '10 (最高)', maxTokens: '8192', temp: '0.5', enabled: true },
                  { key: '2', model: 'gemini-1.5-pro', priority: '5', maxTokens: '4096', temp: '0.7', enabled: true },
                ]}
                columns={[
                  { title: t('agents.engineName'), dataIndex: 'model', key: 'model' },
                  { title: t('agents.priorityLevel'), dataIndex: 'priority', key: 'priority' },
                  { title: t('agents.maxToken'), dataIndex: 'maxTokens', key: 'maxTokens' },
                  { title: t('agents.temperature'), dataIndex: 'temp', key: 'temp' },
                  { title: t('agents.enabledLabel'), dataIndex: 'enabled', key: 'enabled', render: (v: boolean) => v ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined /> },
                ]}
              />
            </Card>

            {/* Sec 5: Tools, MCP & Flow Binds */}
            <Card type="inner" title={<span className="flex items-center gap-1.5"><Plus className="h-4 w-4 text-blue-500" /> 5. {t('agents.toolsBinding')}</span>} size="small">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-semibold mb-2">{t('agents.selectSkills')}</label>
                  <div className="border rounded-lg p-2.5 space-y-2 max-h-[180px] overflow-y-auto">
                    {skills.map(sk => (
                      <label key={sk.id} className="flex items-start gap-2 p-1.5 hover:bg-slate-50 dark:hover:bg-gray-800 rounded cursor-pointer transition">
                        <input
                          type="checkbox"
                          checked={selectedSkills.includes(sk.id)}
                          onChange={() => handleToggleSkillSelection(sk.id)}
                          className="mt-0.5"
                        />
                        <div>
                          <div className="text-xs font-semibold flex items-center gap-1">
                            <span>{sk.name}</span>
                            <Tag className="text-xs" style={{ fontSize: 9, lineHeight: '16px', padding: '0 4px' }}>{sk.category}</Tag>
                          </div>
                          <div className="text-xs mt-0.5" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>{sk.description}</div>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold mb-2">{t('agents.selectMcp')}</label>
                  <div className="border rounded-lg p-2.5 space-y-2 max-h-[180px] overflow-y-auto">
                    {mcpServers.map(srv => (
                      <label key={srv.id} className="flex items-start gap-2 p-1.5 hover:bg-slate-50 dark:hover:bg-gray-800 rounded cursor-pointer transition">
                        <input
                          type="checkbox"
                          checked={selectedMcp.includes(srv.id)}
                          onChange={() => handleToggleMcpSelection(srv.id)}
                          className="mt-0.5"
                        />
                        <div className="flex-1">
                          <div className="text-xs font-semibold flex items-center justify-between gap-1">
                            <span>{srv.name}</span>
                            <Tag color={srv.status === 'connected' ? 'green' : 'red'} style={{ fontSize: 9, lineHeight: '16px', padding: '0 4px' }}>
                              {srv.status === 'connected' ? t('agents.mcpActive') : t('agents.mcpDisconnected')}
                            </Tag>
                          </div>
                          <div className="text-xs mt-0.5" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>{srv.description}</div>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold mb-2">{t('agents.selectFlows')}</label>
                  <div className="border rounded-lg p-2.5 space-y-2 max-h-[180px] overflow-y-auto">
                    {flows.length === 0 ? (
                      <div className="text-xs text-center py-4" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>{t('agents.noFlows')}</div>
                    ) : (
                      flows.map(fl => (
                        <label key={fl.id} className="flex items-start gap-2 p-1.5 hover:bg-slate-50 dark:hover:bg-gray-800 rounded cursor-pointer transition">
                          <input
                            type="checkbox"
                            checked={selectedFlows.includes(fl.id)}
                            onChange={() => handleToggleFlowSelection(fl.id)}
                            className="mt-0.5"
                          />
                          <div className="flex-1">
                            <div className="text-xs font-semibold flex items-center gap-1">
                              <Workflow className="h-3.5 w-3.5 text-blue-500 shrink-0" />
                              <span>{fl.name}</span>
                              <Tag color="blue" style={{ fontSize: 9, lineHeight: '16px', padding: '0 4px' }}>{fl.nodes.length} {t('agents.flowNodes')}</Tag>
                            </div>
                            <div className="text-xs mt-0.5" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>{fl.description}</div>
                          </div>
                        </label>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </Card>

            {/* Sec 6: Visibility & Publish status */}
            <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-lg" style={{ background: isDark ? '#111d2c' : '#f0f5ff' }}>
              <div className="flex items-center gap-4">
                <div>
                  <label className="block text-xs mb-0.5" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>{t('agents.visibilitySetting')}</label>
                  <Select
                    size="small"
                                        value={formVisibility}
                    onChange={(v) => setFormVisibility(v)}
                    options={[
                      { label: t('agents.visibilityMe'), value: 'me' },
                      { label: t('agents.visibilityOrg'), value: 'org' },
                      { label: t('agents.visibilityPublic'), value: 'public' },
                    ]}
                  />
                </div>
                <div>
                  <label className="block text-xs mb-0.5" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>{t('agents.publishVersion')}</label>
                  <Input
                    size="small"
                    value={formVersion}
                    onChange={(e) => setFormVersion(e.target.value)}
                    style={{ width: 80, textAlign: 'center' }}
                    className="font-mono"
                  />
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  type="default"
                  onClick={() => {
                    setFormStatus('draft');
                    setTimeout(() => {
                      const triggerSubmit = document.getElementById('btn-submit-real');
                      if (triggerSubmit) triggerSubmit.click();
                    }, 50);
                  }}
                >
                  {t('agents.saveDraft')}
                </Button>
                <Button
                  type="primary"
                  onClick={() => {
                    setFormStatus('published');
                    setTimeout(() => {
                      const triggerSubmit = document.getElementById('btn-submit-real');
                      if (triggerSubmit) triggerSubmit.click();
                    }, 50);
                  }}
                >
                  {t('agents.publish')}
                </Button>
                <input type="submit" id="btn-submit-real" className="hidden" />
              </div>
            </div>

          </form>
        </Card>
      ) : (
        <div className="space-y-6">
          <Card size="small">
            {/* Toolbar */}
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <div className="flex flex-wrap items-center gap-3">
                <Input
                  prefix={<SearchOutlined />}
                  placeholder={t('agents.searchPlaceholder')}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{ width: 180 }}
                  allowClear
                />
                <Select
                  value={statusFilter}
                  onChange={setStatusFilter}
                  style={{ width: 120 }}
                  options={[
                    { label: t('agents.allStatus'), value: 'all' },
                    { label: t('agents.published'), value: 'published' },
                    { label: t('agents.draft'), value: 'draft' },
                    { label: t('agents.deprecated'), value: 'deprecated' },
                    { label: t('agents.archived'), value: 'archived' },
                  ]}
                />
                <Select
                  value={typeFilter}
                  onChange={setTypeFilter}
                  style={{ width: 120 }}
                  options={[
                    { label: t('agents.allTypes'), value: 'all' },
                    { label: t('agents.conversational'), value: 'conversational' },
                    { label: t('agents.service'), value: 'service' },
                    { label: t('agents.hybrid'), value: 'hybrid' },
                  ]}
                />
                <Select
                  value={tagFilter}
                  onChange={setTagFilter}
                  style={{ width: 120 }}
                  options={[
                    { label: t('agents.allTags'), value: 'all' },
                    ...allTags.map(tag => ({ label: tag, value: tag })),
                  ]}
                />
              </div>

              <Button
                id="btn-new-agent"
                type="primary"
                icon={<PlusOutlined />}
                onClick={handleOpenCreate}
              >
                {t('agents.createAgent')}
              </Button>
            </div>

            {/* Table listing */}
            {filteredAgents.length === 0 ? (
              <Empty
                image={<Bot className="h-10 w-10" style={{ color: isDark ? '#595959' : '#bfbfbf' }} />}
                description={
                  <div>
                    <Title level={5}>{t('agents.noMatchTitle')}</Title>
                    <Paragraph type="secondary">{t('agents.noMatchDesc')}</Paragraph>
                  </div>
                }
              >
                <Button type="primary" onClick={handleOpenCreate}>{t('agents.createNewAgent')}</Button>
              </Empty>
            ) : (
              <Table
                dataSource={filteredAgents.map(a => ({ ...a, key: a.id }))}
                columns={columns}
                pagination={false}
                size="middle"
                onRow={(record) => ({
                  onClick: () => {
                    if (focusedAgentId === record.id) {
                      setFocusedAgentId(null);
                    } else {
                      setFocusedAgentId(record.id);
                    }
                  },
                  style: { cursor: 'pointer' },
                })}
                rowClassName={(record) =>
                  focusedAgentId === record.id ? 'ant-table-row-selected' : ''
                }
              />
            )}
          </Card>

          {/* AGENT DETAILS DRAWER PANEL */}
          {focusAgent && (
            <ResizableModal
              open={!!focusAgent}
              onCancel={() => setFocusedAgentId(null)}
              width={1000}
              title={
                <div className="flex items-center gap-2">
                  <Bot className="h-5 w-5 text-blue-500" />
                  <span className="text-lg font-bold">{focusAgent.name}</span>
                  <Tag color="blue">v{focusAgent.version}</Tag>
                  <Tag color={getStatusColor(focusAgent.status)}>{getStatusLabel(focusAgent.status)}</Tag>
                </div>
              }
              footer={
                <Space>
                  {focusAgent.status === 'published' && (
                    <Button
                      type="primary"
                      icon={<PlayCircleOutlined />}
                      onClick={() => addChat(focusAgent.id)}
                    >
                      {t('agents.openChat')}
                    </Button>
                  )}
                  <Button icon={<EditOutlined />} onClick={() => handleOpenEdit(focusAgent)}>
                    {t('agents.editPrompt')}
                  </Button>
                  <Button onClick={() => setFocusedAgentId(null)}>{t('agents.closeLabel')}</Button>
                </Space>
              }
              draggable
              resizable
            >
              <Paragraph type="secondary" className="mb-4">{focusAgent.description}</Paragraph>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Left column */}
                <div className="space-y-4">
                  <Card type="inner" size="small" title={t('agents.promptAndPlan')}>
                    <pre className="whitespace-pre-wrap font-mono text-xs p-2 rounded max-h-[160px] overflow-y-auto" style={{ background: isDark ? '#141414' : '#fafafa' }}>
                      {focusAgent.systemPrompt}
                    </pre>
                    <div className="text-xs mt-2" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>
                      {t('agents.roleTone')} {focusAgent.persona.role} | {t('agents.tonePrefix')} {focusAgent.persona.tone}
                    </div>
                  </Card>

                  <Card type="inner" size="small" title={t('agents.constraintsTitle')}>
                    <ul className="list-disc pl-4 space-y-1">
                      {focusAgent.persona.constraints.map((con, idx) => (
                        <li key={idx} className="text-xs">{t('agents.mandatory')} {con}</li>
                      ))}
                    </ul>
                  </Card>
                </div>

                {/* Right column */}
                <div className="space-y-4">
                  <Card type="inner" size="small" title={`${t('agents.aggregateTools')} (${getAggregateTools(focusAgent).length})`}>
                    {getAggregateTools(focusAgent).length === 0 ? (
                      <Empty description={t('agents.noTools')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    ) : (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-[160px] overflow-y-auto">
                        {getAggregateTools(focusAgent).map((tool, i) => (
                          <div key={i} className="p-2 rounded border flex items-center justify-between">
                            <div>
                              <div className="font-mono text-xs font-bold">{tool.name}</div>
                              <div className="text-xs" style={{ color: isDark ? '#737373' : '#8c8c8c', fontSize: 9 }}>{t('agents.source')} {tool.origin}</div>
                            </div>
                            <Tag color={tool.type === 'skill' ? 'blue' : 'purple'} style={{ fontSize: 9 }}>{tool.type === 'skill' ? 'Skill' : 'MCP'}</Tag>
                          </div>
                        ))}
                      </div>
                    )}
                  </Card>

                  <Card
                    type="inner"
                    size="small"
                    title={t('agents.recentTasks')}
                    extra={<Button type="link" size="small" onClick={() => setActiveTab('tasks')}>{t('agents.goTaskBoard')}</Button>}
                  >
                    {focusRecentTasks.length === 0 ? (
                      <Empty description={t('agents.noScheduleLog')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    ) : (
                      <div className="space-y-1.5 max-h-[140px] overflow-y-auto">
                        {focusRecentTasks.map(tk => (
                          <div
                            key={tk.id}
                            onClick={() => {
                              setFocusedTaskId(tk.id);
                              setActiveTab('tasks');
                            }}
                            className="flex items-center justify-between p-2 rounded hover:bg-slate-50 dark:hover:bg-gray-800 cursor-pointer transition border"
                            style={{ borderColor: isDark ? '#303030' : '#f0f0f0' }}
                          >
                            <div className="font-medium text-xs flex-1 pr-4">{tk.title}</div>
                            <div className="flex items-center gap-2 shrink-0">
                              <Tag color={tk.status === 'completed' ? 'green' : 'blue'} style={{ fontSize: 9 }}>
                                {tk.status === 'completed' ? t('agents.completed') : `${t('agents.inProgress')}(${tk.progress}%)`}
                              </Tag>
                              <ChevronRight className="h-3 w-3" style={{ color: isDark ? '#595959' : '#bfbfbf' }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </Card>
                </div>
              </div>

            </ResizableModal>
          )}

        </div>
      )}

    </div>
  );
};
