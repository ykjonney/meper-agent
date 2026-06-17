import React, { useState } from 'react';
import { useAppState } from '../AppContext';
import { Skill } from '../types';
import { useTheme } from '../ThemeContext';
import {
  Plus, Search, Terminal, ArrowLeft, Play, Cpu, Layers, HelpCircle,
  Trash2, Edit, Check, Settings, Copy, Code,
  ClipboardList, Pencil, Radio
} from 'lucide-react';
import { useTranslation } from '../LocaleContext';
import {
  Table, Tag, Button, Input, Space, Card, Tooltip, Empty, Typography,
  Popconfirm, message, Segmented, Badge
} from 'antd';
import {
  PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined,
  PlayCircleOutlined, CodeOutlined, CopyOutlined, LoadingOutlined,
  CheckCircleOutlined, ArrowLeftOutlined, ExperimentOutlined,
  CodeSandboxOutlined as TerminalOutlined
} from '@ant-design/icons';
import { ResizableModal } from './ResizableModal';

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;

export const SkillsPage: React.FC = () => {
  const {
    skills,
    addSkill,
    updateSkill,
    deleteSkill,
    focusedSkillId,
    setFocusedSkillId,
    editingSkillId,
    setEditingSkillId,
    showNotification
  } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();

  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');

  // Interactive Test Execution state
  const [testPayload, setTestPayload] = useState('');
  const [testResult, setTestResult] = useState('');
  const [isRunningTest, setIsRunningTest] = useState(false);
  const [testDuration, setTestDuration] = useState<number | null>(null);

  // Form states for Skill editor
  const [formName, setFormName] = useState('');
  const [formDesc, setFormDesc] = useState('');
  const [formCategory, setFormCategory] = useState<Skill['category']>('Custom');
  const [formTags, setFormTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState('');
  const [formSchema, setFormSchema] = useState('');
  const [formTestParams, setFormTestParams] = useState('');
  const [formMockOutput, setFormMockOutput] = useState('');
  const [formVersion, setFormVersion] = useState('1.0.0');

  // Filters inputs
  const filteredSkills = skills.filter(sk => {
    const matchesSearch = sk.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                          sk.description.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesCat = categoryFilter === 'all' || sk.category === categoryFilter;
    return matchesSearch && matchesCat;
  });

  const handleOpenCreate = () => {
    setFormName('finance_forechecker');
    setFormDesc('商业报表预合并计算及多维预算合规核验算子。');
    setFormCategory('Custom');
    setFormTags(['财务', '校验']);
    setFormSchema(JSON.stringify({
      records: { type: "array", description: "List of transaction items" },
      threshold: { type: "number", default: 10000 }
    }, null, 2));
    setFormTestParams(JSON.stringify({
      records: [{ id: 1, amount: 15400 }],
      threshold: 10000
    }, null, 2));
    setFormMockOutput(JSON.stringify({
      valid: false,
      conformance: 0,
      violations: [
        { id: 1, amount: 15400, cap: 10000, message: "Amount exceeds target limits" }
      ]
    }, null, 2));
    setFormVersion('1.0.0');
    setEditingSkillId('new');
    setFocusedSkillId(null);
  };

  const handleOpenEdit = (sk: Skill) => {
    setFormName(sk.name);
    setFormDesc(sk.description);
    setFormCategory(sk.category);
    setFormTags(sk.tags);
    setFormSchema(sk.schema);
    setFormTestParams(sk.testParams);
    setFormMockOutput(sk.mockOutput);
    setFormVersion(sk.version);
    setEditingSkillId(sk.id);
    setFocusedSkillId(null);
  };

  // 改由 Modal footer 的保存按钮 onClick 触发, 不再依赖 <form onSubmit>
  const handleSaveSkill = () => {
    if (!formName.trim()) {
      message.error(t('skills.nameRequired') || '请填写 Skill 名称');
      return;
    }

    try {
      JSON.parse(formSchema);
      JSON.parse(formTestParams);
      JSON.parse(formMockOutput);
    } catch (err: any) {
      message.error(`${t('skills.jsonParseError')}${err.message}`);
      return;
    }

    const payloadObj = {
      name: formName,
      description: formDesc,
      type: 'Function' as const,
      category: formCategory,
      version: formVersion,
      tags: formTags,
      schema: formSchema,
      testParams: formTestParams,
      mockOutput: formMockOutput
    };

    if (editingSkillId === 'new') {
      const created = addSkill(payloadObj);
      setEditingSkillId(null);
      setFocusedSkillId(created.id);
    } else if (editingSkillId) {
      updateSkill({
        ...payloadObj,
        id: editingSkillId
      });
      setEditingSkillId(null);
      setFocusedSkillId(editingSkillId);
    }
  };

  // Safe mock run executor
  const runInteractiveTest = (sk: Skill) => {
    setIsRunningTest(true);
    setTestResult('');
    setTestDuration(null);

    setTimeout(() => {
      try {
        JSON.parse(testPayload);
        setTestResult(sk.mockOutput);
        setTestDuration(Math.floor(Math.random() * 300) + 120);
        showNotification('success', `Skill「${sk.name}」${t('skills.testSuccess')}`);
      } catch (err: any) {
        setTestResult(JSON.stringify({
          status: "failed",
          phase: "parse",
          error: `JSON Parameter Malformed: ${err.message}`
        }, null, 2));
        showNotification('error', t('skills.testFailed'));
      } finally {
        setIsRunningTest(false);
      }
    }, 1400);
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    showNotification('success', t('skills.copySuccess'));
  };

  const focusSkill = skills.find(s => s.id === focusedSkillId);

  // Sync test inputs when focused node changes
  React.useEffect(() => {
    if (focusSkill) {
      setTestPayload(focusSkill.testParams);
      setTestResult('');
      setTestDuration(null);
    }
  }, [focusedSkillId]);

  // Table columns
  const columns = [
    {
      title: t('skills.skillName'),
      dataIndex: 'name',
      key: 'name',
      render: (text: string) => <Text code className="text-xs font-mono">{text}</Text>,
    },
    {
      title: t('skills.descLabel'),
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (text: string) => <Text className="text-xs">{text}</Text>,
    },
    {
      title: t('skills.categoryLabel'),
      dataIndex: 'category',
      key: 'category',
      width: 120,
      render: (cat: Skill['category']) => (
        <Tag color={cat === 'Built-in' ? 'blue' : 'purple'}>
          {cat === 'Built-in' ? t('skills.builtIn') : t('skills.custom')}
        </Tag>
      ),
    },
    {
      title: t('skills.versionLabel'),
      dataIndex: 'version',
      key: 'version',
      width: 80,
      render: (v: string) => <Text code className="text-xs">v{v}</Text>,
    },
    {
      title: t('skills.actionsLabel'),
      key: 'actions',
      width: 200,
      render: (_: unknown, record: Skill) => (
        <Space size={4}>
          <Button
            type="primary"
            size="small"
            ghost
            icon={<ExperimentOutlined />}
            onClick={() => setFocusedSkillId(record.id)}
          >
            {t('skills.testRun')}
          </Button>
          {record.category === 'Custom' && (
            <>
              <Tooltip title={t('skills.editTooltip')}>
                <Button
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => handleOpenEdit(record)}
                />
              </Tooltip>
              <Popconfirm
                title={t('skills.confirmDelete').replace('{name}', record.name)}
                onConfirm={() => deleteSkill(record.id)}
                okText={t('common.confirm')}
                cancelText={t('common.cancel')}
              >
                <Tooltip title={t('skills.revokeTooltip')}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Tooltip>
              </Popconfirm>
            </>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div className="px-4 py-6">
      <div className="space-y-6">
        {/* 列表(始终显示) */}
        <Card size="small">
          {/* Toolbar */}
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div className="flex flex-wrap items-center gap-3">
              <Input
                prefix={<SearchOutlined />}
                placeholder={t('skills.searchPlaceholder')}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ width: 200 }}
                allowClear
              />
              <Segmented
                value={categoryFilter}
                onChange={(v) => setCategoryFilter(v as string)}
                options={[
                  { label: t('skills.allSkills'), value: 'all' },
                  { label: t('skills.builtIn'), value: 'Built-in' },
                  { label: t('skills.custom'), value: 'Custom' },
                ]}
              />
            </div>
            <Button
              id="btn-register-skill"
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleOpenCreate}
            >
              {t('skills.registerSkill')}
            </Button>
          </div>

          {/* Table listing */}
          <Table
            dataSource={filteredSkills.map(sk => ({ ...sk, key: sk.id }))}
            columns={columns}
            pagination={false}
            size="middle"
            onRow={(record) => ({
              onClick: () => {
                if (focusedSkillId === record.id) {
                  setFocusedSkillId(null);
                } else {
                  setFocusedSkillId(record.id);
                }
              },
              style: { cursor: 'pointer' },
            })}
            rowClassName={(record) =>
              focusedSkillId === record.id ? 'ant-table-row-selected' : ''
            }
            locale={{ emptyText: <Empty description={t('skills.noMatch')} /> }}
          />
        </Card>

        {/* 编辑/创建 Skill 弹窗 */}
        <ResizableModal
          open={!!editingSkillId}
          onCancel={() => setEditingSkillId(null)}
          width={720}
          minWidth={480}
          draggable
          resizable
          destroyOnHidden
          title={
            <div className="flex items-center gap-2">
              {editingSkillId === 'new' ? (
                <>
                  <ExperimentOutlined className="text-blue-500" />
                  <span>{t('skills.registerNew')}</span>
                </>
              ) : (
                <>
                  <EditOutlined className="text-blue-500" />
                  <span>{t('skills.editSkill')}: {formName}</span>
                </>
              )}
            </div>
          }
          footer={
            <div className="flex gap-2 justify-end">
              <Button onClick={() => setEditingSkillId(null)}>{t('common.cancel')}</Button>
              <Button type="primary" onClick={handleSaveSkill}>{t('skills.saveSkill')}</Button>
            </div>
          }
        >
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold mb-1">{t('skills.sysNameLabel')} <span className="text-red-500">*</span></label>
                <Input
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder="例如: image_cropper, s3_uploader"
                  className="font-mono"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">{t('skills.versionPhysical')}</label>
                <Input
                  value={formVersion}
                  onChange={(e) => setFormVersion(e.target.value)}
                  placeholder="1.0.0"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold mb-1">{t('skills.funcDescLabel')}</label>
              <TextArea
                value={formDesc}
                onChange={(e) => setFormDesc(e.target.value)}
                placeholder={t('skills.funcDescPlaceholder')}
                rows={2}
              />
            </div>

            <div>
              <label className="block text-xs font-semibold mb-1">{t('skills.schemaLabel')}</label>
              <TextArea
                value={formSchema}
                onChange={(e) => setFormSchema(e.target.value)}
                rows={4}
                className="font-mono text-xs"
                style={{ background: isDark ? '#141414' : '#1f1f1f', color: isDark ? '#d9d9d9' : '#d9d9d9' }}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold mb-1">{t('skills.testParamsLabel')}</label>
                <TextArea
                  value={formTestParams}
                  onChange={(e) => setFormTestParams(e.target.value)}
                  rows={4}
                  className="font-mono text-xs"
                  style={{ background: isDark ? '#141414' : '#1f1f1f', color: isDark ? '#d9d9d9' : '#d9d9d9' }}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">{t('skills.mockResponseLabel')}</label>
                <TextArea
                  value={formMockOutput}
                  onChange={(e) => setFormMockOutput(e.target.value)}
                  rows={4}
                  className="font-mono text-xs"
                  style={{ background: isDark ? '#141414' : '#1f1f1f', color: isDark ? '#d9d9d9' : '#d9d9d9' }}
                />
              </div>
            </div>
          </div>
        </ResizableModal>

        {/* 测试控制台弹窗 */}
        <ResizableModal
          open={!!focusSkill}
          onCancel={() => setFocusedSkillId(null)}
          width={1100}
          minWidth={640}
          draggable
          resizable
          destroyOnHidden
          title={
            <div className="flex items-center gap-1.5">
              <TerminalOutlined style={{ color: '#1677ff' }} />
              <span>{t('skills.testWorkspace')}: {focusSkill?.name}</span>
            </div>
          }
          footer={
            <Button onClick={() => setFocusedSkillId(null)}>{t('skills.closeLabel')}</Button>
          }
        >
          {focusSkill && (
            <>
              <div className="flex flex-wrap items-center gap-x-4 mb-4 pb-4 border-b" style={{ borderColor: isDark ? '#303030' : '#f0f0f0' }}>
                <Tag color={focusSkill.category === 'Built-in' ? 'blue' : 'purple'}>
                  {focusSkill.category === 'Built-in' ? t('skills.builtIn') : t('skills.custom')}
                </Tag>
                <Text type="secondary" className="text-xs">{`${t('skills.typeLabel')}: Function`}</Text>
                <Text type="secondary" className="text-xs">{t('skills.versionLabel')}: v{focusSkill.version}</Text>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

                {/* Left Parameter Schema */}
                <div className="space-y-4">
                  <Card type="inner" size="small" title={t('skills.inputSchema')}>
                    <pre className="font-mono text-xs overflow-x-auto whitespace-pre max-h-[160px] leading-relaxed">
                      {focusSkill.schema}
                    </pre>
                  </Card>

                  <div className="space-y-1.5">
                    <div className="font-bold text-xs flex items-center justify-between">
                      <span className="flex items-center gap-1.5">
                        <Pencil className="h-3.5 w-3.5" style={{ color: isDark ? '#737373' : '#8c8c8c' }} />
                        {t('skills.testPayloadLabel')}
                      </span>
                      <span
                        onClick={() => setTestPayload(focusSkill.testParams)}
                        className="text-xs cursor-pointer"
                        style={{ color: '#1677ff', fontSize: 10 }}
                      >
                        {t('skills.restoreDefault')}
                      </span>
                    </div>
                    <TextArea
                      value={testPayload}
                      onChange={(e) => setTestPayload(e.target.value)}
                      rows={5}
                      className="font-mono text-xs"
                    />
                    <Text type="secondary" className="text-xs italic">{t('skills.payloadHint')}</Text>
                  </div>

                  <Button
                    type="primary"
                    block
                    icon={isRunningTest ? <LoadingOutlined /> : <PlayCircleOutlined />}
                    onClick={() => runInteractiveTest(focusSkill)}
                    disabled={isRunningTest}
                    size="large"
                  >
                    {isRunningTest ? t('skills.executing') : t('skills.executeCommand')}
                  </Button>
                </div>

                {/* Right stdout terminal output area */}
                <Card type="inner" size="small" className="flex flex-col min-h-[340px]">
                  <div className="flex items-center justify-between mb-2 pb-2 border-b" style={{ borderColor: isDark ? '#303030' : '#f0f0f0' }}>
                    <span className="font-mono text-xs uppercase tracking-wider flex items-center gap-1.5">
                      <TerminalOutlined /> {t('skills.stdoutConsole')}
                    </span>
                    <Space>
                      {testDuration && (
                        <Text type="secondary" className="text-xs flex items-center gap-1">
                          <CheckCircleOutlined /> {t('skills.duration')}: {testDuration}ms
                        </Text>
                      )}
                      <Tooltip title={t('skills.copyLabel')}>
                        <Button
                          type="text"
                          size="small"
                          icon={<CopyOutlined />}
                          onClick={() => copyToClipboard(testResult || t('skills.noOutput'))}
                        />
                      </Tooltip>
                    </Space>
                  </div>

                  <div className="flex-1 overflow-auto font-mono text-xs leading-relaxed min-h-[200px] max-h-[300px]" style={{ color: '#52c41a' }}>
                    {isRunningTest ? (
                      <div className="animate-pulse italic" style={{ color: isDark ? '#595959' : '#8c8c8c' }}>
                        [AI-STUDIO EXECUTOR] Spawning sub-process container sandbox...<br />
                        [AI-STUDIO EXECUTOR] Binding volume workspace mount /workspace...<br />
                        [AI-STUDIO EXECUTOR] Running validation algorithms...
                      </div>
                    ) : testResult ? (
                      <pre className="whitespace-pre overflow-x-auto">{testResult}</pre>
                    ) : (
                      <div className="italic" style={{ color: isDark ? '#595959' : '#8c8c8c' }}>
                        // {t('skills.terminalReady')}
                      </div>
                    )}
                  </div>

                  <div className="border-t pt-3 text-xs font-mono flex justify-between items-center" style={{ borderColor: isDark ? '#303030' : '#f0f0f0', color: isDark ? '#595959' : '#8c8c8c' }}>
                    <span>SHELL DRIVER: STABLE</span>
                    <span>UTF-8 ENCODING</span>
                  </div>
                </Card>

              </div>
            </>
          )}
        </ResizableModal>
      </div>
    </div>
  );
};
