import React, { useState } from 'react';
import { useAppState } from '../AppContext';
import { PresetNode } from '../types';
import { useTheme } from '../ThemeContext';
import { useTranslation } from '../LocaleContext';
import { Layers, Bot, Eye, HelpCircle } from 'lucide-react';
import {
  Table, Tag, Button, Input, Select, Space, Modal, Card,
  Empty, Typography, Popconfirm, message
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined,
  CloseOutlined, SaveOutlined, EyeOutlined
} from '@ant-design/icons';

const { TextArea } = Input;
const { Title, Text } = Typography;

export const PresetNodesPage: React.FC = () => {
  const {
    presetNodes,
    agents,
    addPresetNode,
    updatePresetNode,
    deletePresetNode,
    showNotification
  } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();

  const [editingNode, setEditingNode] = useState<PresetNode | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [showConfigId, setShowConfigId] = useState<string | null>(null);

  // Form State
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [agentId, setAgentId] = useState('');
  const [preFilledInput, setPreFilledInput] = useState('{\n  \n}');

  const startCreate = () => {
    setName('');
    setDescription('');
    setAgentId(agents[0]?.id || '');
    setPreFilledInput(JSON.stringify({ parameter: "value" }, null, 2));
    setIsCreating(true);
    setEditingNode(null);
  };

  const startEdit = (node: PresetNode) => {
    setEditingNode(node);
    setName(node.name);
    setDescription(node.description);
    setAgentId(node.agentId);
    setPreFilledInput(node.preFilledInput);
    setIsCreating(false);
  };

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      showNotification('error', t('nodes.nameRequired'));
      return;
    }
    if (!agentId) {
      showNotification('error', t('nodes.agentRequired'));
      return;
    }

    try {
      JSON.parse(preFilledInput);
    } catch {
      showNotification('error', t('nodes.jsonInvalid'));
      return;
    }

    if (editingNode) {
      updatePresetNode({
        ...editingNode,
        name,
        description,
        agentId,
        preFilledInput
      });
    } else {
      addPresetNode({
        name,
        description,
        agentId,
        preFilledInput
      });
    }

    closeDrawer();
  };

  const closeDrawer = () => {
    setIsCreating(false);
    setEditingNode(null);
  };

  // Table columns
  const columns = [
    {
      title: t('nodes.columnName'),
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: PresetNode) => (
        <div>
          <div className="font-semibold text-sm">{text}</div>
          <Text type="secondary" className="text-xs font-mono">{record.id}</Text>
        </div>
      ),
    },
    {
      title: t('nodes.columnAgent'),
      dataIndex: 'agentId',
      key: 'agentId',
      width: 180,
      render: (agentIdStr: string) => {
        const agentObj = agents.find(a => a.id === agentIdStr);
        if (agentObj) {
          return (
            <Tag color="blue" icon={<Bot className="h-3 w-3 inline-block mr-1" style={{ verticalAlign: -2 }} />}>
              {agentObj.name}
            </Tag>
          );
        }
        return <Tag color="red">{t('nodes.unboundAgent')}</Tag>;
      },
    },
    {
      title: t('nodes.columnDesc'),
      dataIndex: 'description',
      key: 'description',
      render: (desc: string, record: PresetNode) => {
        const isShowingConfig = showConfigId === record.id;
        return (
          <div className="flex flex-col gap-1.5">
            <Text className="text-xs">{desc || t('nodes.noDesc')}</Text>
            <Button
              type="link"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => setShowConfigId(isShowingConfig ? null : record.id)}
              className="self-start"
              style={{ padding: 0, height: 'auto', fontSize: 12 }}
            >
              {isShowingConfig ? t('nodes.collapsePreInput') : t('nodes.viewPreInput')}
            </Button>

            {isShowingConfig && (
              <pre
                className="p-2.5 rounded text-[10.5px] font-mono border border-dashed overflow-auto max-h-48 whitespace-pre"
                style={{
                  background: isDark ? '#141414' : '#f5f5f5',
                  borderColor: isDark ? '#303030' : '#d9d9d9',
                  color: isDark ? '#a6a6a6' : '#595959'
                }}
              >
                {record.preFilledInput}
              </pre>
            )}
          </div>
        );
      },
    },
    {
      title: t('nodes.columnActions'),
      key: 'actions',
      width: 120,
      render: (_: unknown, record: PresetNode) => (
        <Space size={4}>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => startEdit(record)}
          />
          <Popconfirm
            title={t('nodes.confirmDelete').replace('{name}', record.name)}
            onConfirm={() => deletePresetNode(record.id)}
            okText={t('nodes.okText')}
            cancelText={t('nodes.cancelText')}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className="px-4 py-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {/* Table list */}
        <div className={`transition-all duration-200 ${(isCreating || editingNode) ? 'lg:col-span-2' : 'lg:col-span-3'}`}>
          <Card size="small">
            {/* Toolbar */}
            <div className="flex items-center justify-between mb-4">
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={startCreate}
              >
                {t('nodes.createNode')}
              </Button>
            </div>

            {presetNodes.length === 0 ? (
              <Empty
                image={<Layers className="h-10 w-10" style={{ color: isDark ? '#595959' : '#bfbfbf' }} />}
                description={
                  <div>
                    <Title level={5}>{t('nodes.emptyTitle')}</Title>
                    <Text type="secondary">{t('nodes.emptyDesc')}</Text>
                  </div>
                }
              >
                <Button type="primary" onClick={startCreate}>{t('nodes.createNow')}</Button>
              </Empty>
            ) : (
              <Table
                dataSource={presetNodes.map(n => ({ ...n, key: n.id }))}
                columns={columns}
                pagination={false}
                size="middle"
              />
            )}
          </Card>
        </div>

        {/* Form Panel */}
        {(isCreating || editingNode) && (
          <div className="lg:col-span-1">
            <Card
              title={
                <div className="flex items-center gap-2">
                  <Layers className="h-4 w-4 text-blue-500" />
                  <span>{editingNode ? t('nodes.editTitle') : t('nodes.createTitle')}</span>
                </div>
              }
              extra={
                <Button type="text" icon={<CloseOutlined />} onClick={closeDrawer} />
              }
            >
              <form onSubmit={handleSave} className="flex flex-col gap-4">
                <div>
                  <label className="block text-xs font-semibold mb-1">
                    {t('nodes.nameLabel')} <span className="text-red-500">*</span>
                  </label>
                  <Input
                    value={name}
                    onChange={e => setName(e.target.value)}
                    placeholder={t('nodes.namePlaceholder')}
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold mb-1">
                    {t('nodes.agentLabel')} <span className="text-red-500">*</span>
                  </label>
                  <Select
                    value={agentId || undefined}
                    onChange={v => setAgentId(v)}
                    placeholder={t('nodes.agentPlaceholder')}
                    className="w-full"
                                        options={agents.map(a => ({
                      label: `${a.name} (${a.persona.role})`,
                      value: a.id
                    }))}
                  />
                  <Text type="secondary" className="text-xs mt-1 block">
                    {t('nodes.agentHint')}
                  </Text>
                </div>

                <div>
                  <label className="block text-xs font-semibold mb-1">
                    {t('nodes.preInputLabel')} <span className="text-red-500">*</span>
                  </label>
                  <TextArea
                    rows={6}
                    value={preFilledInput}
                    onChange={e => setPreFilledInput(e.target.value)}
                    placeholder={t('nodes.preInputPlaceholder')}
                    className="font-mono text-xs"
                  />
                  <Text type="secondary" className="text-xs mt-1 block">
                    {t('nodes.preInputHint')}
                  </Text>
                </div>

                <div>
                  <label className="block text-xs font-semibold mb-1">{t('nodes.funcDescLabel')}</label>
                  <TextArea
                    rows={2}
                    value={description}
                    onChange={e => setDescription(e.target.value)}
                    placeholder={t('nodes.funcDescPlaceholder')}
                  />
                </div>

                <div className="flex items-center gap-2 mt-2 pt-4 border-t" style={{ borderColor: isDark ? '#303030' : '#f0f0f0' }}>
                  <Button type="primary" htmlType="submit" icon={<SaveOutlined />} className="flex-1">
                    {t('nodes.saveNode')}
                  </Button>
                  <Button onClick={closeDrawer}>{t('nodes.cancelText')}</Button>
                </div>
              </form>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
};
