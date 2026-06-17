import React, { useState } from 'react';
import { useAppState } from '../AppContext';
import { MCPServer } from '../types';
import { useTheme } from '../ThemeContext';
import {
  Plus, Search, Cpu, Play, Settings, RefreshCw, Layers, ArrowLeft,
  Trash2, Edit, Check, Clipboard, Wifi, XOctagon, Terminal, Wrench
} from 'lucide-react';
import { useTranslation } from '../LocaleContext';
import {
  Table, Tag, Button, Input, Space, Card, Tooltip, Empty, Typography,
  Badge, Descriptions, Timeline, Popconfirm, Radio, message, Collapse
} from 'antd';
import {
  PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined,
  PlayCircleOutlined, ReloadOutlined, ApiOutlined, ToolOutlined,
  ArrowLeftOutlined, CheckCircleOutlined, CloseCircleOutlined,
  CodeOutlined, LoadingOutlined, LinkOutlined, DisconnectOutlined,
  CopyOutlined
} from '@ant-design/icons';
import { ResizableModal } from './ResizableModal';

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;

export const MCPServersPage: React.FC = () => {
  const {
    mcpServers,
    addMCPServer,
    updateMCPServer,
    deleteMCPServer,
    toggleMCPConnection,
    triggerMCPDiscovery,
    focusedMCPServerId,
    setFocusedMCPServerId,
    editingMCPServerId,
    setEditingMCPServerId,
    showNotification
  } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();

  const [searchQuery, setSearchQuery] = useState('');

  // Form States for creating/editing MCP Server
  const [formName, setFormName] = useState('');
  const [formDesc, setFormDesc] = useState('');
  const [formType, setFormType] = useState<MCPServer['connectionType']>('STDIO');

  // STDIO attributes
  const [formCmd, setFormCmd] = useState('npx');
  const [formArgsString, setFormArgsString] = useState('-y @modelcontextprotocol/server-filesystem /workspace');
  const [formEnvString, setFormEnvString] = useState('ALLOWED_ROOT=/workspace');

  // SSE/HTTP attributes
  const [formUrl, setFormUrl] = useState('http://localhost:8080/mcp');
  const [formHeadersString, setFormHeadersString] = useState('Authorization=Bearer db-secret-token');

  const [formTimeout, setFormTimeout] = useState(30);
  const [formReconnect, setFormReconnect] = useState(true);
  const [formMaxRetries, setFormMaxRetries] = useState(3);

  // Tool interactive executing cockpit state inside detail drawer
  const [activeTestTool, setActiveTestTool] = useState<{ name: string; schema: string } | null>(null);
  const [toolTestPayload, setToolTestPayload] = useState('{\n  "path": "/workspace/demo.txt"\n}');
  const [toolTestStdout, setToolTestStdout] = useState('');
  const [isCallingTool, setIsCallingTool] = useState(false);

  const filteredServers = mcpServers.filter(srv => {
    return srv.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
           srv.description.toLowerCase().includes(searchQuery.toLowerCase());
  });

  const getStatusColor = (status: MCPServer['status']): string => {
    switch (status) {
      case 'connected': return 'green';
      case 'connecting': return 'gold';
      case 'disconnected': return 'red';
    }
  };

  const getStatusLabel = (status: MCPServer['status']) => {
    switch (status) {
      case 'connected': return t('mcp.connected');
      case 'connecting': return t('mcp.connecting');
      case 'disconnected': return t('mcp.disconnected');
    }
  };

  const handleOpenCreate = () => {
    setFormName('web-scraper-mcp');
    setFormDesc('高效率网页抓取及正文元标记自动剥离 MCP 节点。');
    setFormType('SSE');
    setFormCmd('npx');
    setFormArgsString('-y @modelcontextprotocol/server-webscraper');
    setFormEnvString('CONCURRENCY_LIMS=5');
    setFormUrl('https://api.scraper.org/mcp/sse');
    setFormHeadersString('X-API-KEY=scraper-master-secret');
    setFormTimeout(30);
    setFormReconnect(true);
    setFormMaxRetries(3);
    setEditingMCPServerId('new');
    setFocusedMCPServerId(null);
  };

  const handleOpenEdit = (srv: MCPServer) => {
    setFormName(srv.name);
    setFormDesc(srv.description);
    setFormType(srv.connectionType);
    setFormCmd(srv.config.command || 'npx');
    setFormArgsString(srv.config.args ? srv.config.args.join(' ') : '');
    setFormEnvString(srv.config.env ? srv.config.env.map(e => `${e.key}=${e.value}`).join('\n') : '');
    setFormUrl(srv.config.url || '');
    setFormHeadersString(srv.config.headers ? srv.config.headers.map(h => `${h.key}=${h.value}`).join('\n') : '');
    setFormTimeout(srv.config.timeout || 30);
    setFormReconnect(srv.config.reconnect !== false);
    setFormMaxRetries(srv.config.maxRetries || 3);
    setEditingMCPServerId(srv.id);
    setFocusedMCPServerId(null);
  };

  const handleSaveServer = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formName.trim()) return;

    const compiledEnv = formEnvString.trim().split('\n').filter(Boolean).map(line => {
      const parts = line.split('=');
      return { key: parts[0]?.trim() || '', value: parts[1]?.trim() || '' };
    });

    const compiledHeaders = formHeadersString.trim().split('\n').filter(Boolean).map(line => {
      const parts = line.split('=');
      return { key: parts[0]?.trim() || '', value: parts[1]?.trim() || '' };
    });

    const newConf = {
      command: formType === 'STDIO' ? formCmd : undefined,
      args: formType === 'STDIO' ? formArgsString.split(' ').filter(Boolean) : undefined,
      env: formType === 'STDIO' ? compiledEnv : undefined,
      url: formType !== 'STDIO' ? formUrl : undefined,
      headers: formType !== 'STDIO' ? compiledHeaders : undefined,
      timeout: formTimeout,
      reconnect: formReconnect,
      maxRetries: formMaxRetries
    };

    const initialTools = formType === 'STDIO' ? [
      { name: 'scrape_web', description: 'Scrape raw markup from address', schema: '{"url":"string"}' },
      { name: 'parse_markdown', description: 'Strip tags to standard md', schema: '{"html":"string"}' }
    ] : [];

    const defaultLogs = [
      {
        time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
        fromStatus: 'disconnected',
        toStatus: 'disconnected',
        message: 'Platform initialized container configuration bindings.'
      }
    ];

    const payloadObj = {
      name: formName,
      description: formDesc,
      status: 'disconnected' as const,
      connectionType: formType,
      lastConnected: t('mcp.never'),
      toolsCount: initialTools.length,
      resourcesCount: 0,
      promptsCount: 0,
      tools: initialTools,
      config: newConf,
      logs: defaultLogs
    };

    if (editingMCPServerId === 'new') {
      const created = addMCPServer(payloadObj);
      setEditingMCPServerId(null);
      setFocusedMCPServerId(created.id);
    } else if (editingMCPServerId) {
      const currentObj = mcpServers.find(s => s.id === editingMCPServerId);
      updateMCPServer({
        ...payloadObj,
        status: currentObj ? currentObj.status : 'disconnected',
        logs: currentObj ? currentObj.logs : defaultLogs,
        id: editingMCPServerId
      });
      setEditingMCPServerId(null);
      setFocusedMCPServerId(editingMCPServerId);
    }
  };

  // Simulated tool call tester execution
  const runToolExecutionTrial = (toolName: string) => {
    setIsCallingTool(true);
    setToolTestStdout('');

    setTimeout(() => {
      try {
        JSON.parse(toolTestPayload);

        const mockResp = toolName === 'read_file' ? {
          filepath: "/workspace/demo.txt",
          content: "[MOCK MCP CONTENTS]\nThis file is a placeholder read from the filesystem-mcp container. Standard read success.\nLine 2: 2540 transactions tracked."
        } : toolName === 'write_file' ? {
          filepath: "/workspace/demo.txt",
          status: "written",
          bytes: 45
        } : {
          status: "success",
          found_items: ["demo.txt", "package.json", "drizzle.config.ts"]
        };

        setToolTestStdout(JSON.stringify({
          pid: Math.floor(Math.random() * 5000) + 1200,
          status: "success",
          exit_code: 0,
          stdout: mockResp
        }, null, 2));

        showNotification('success', `MCP Tool「${toolName}」${t('mcp.toolCallSuccess')}`);
      } catch (err: any) {
        setToolTestStdout(JSON.stringify({
          status: "failed",
          error: `JSON Input Parse Failure: ${err.message}`
        }, null, 2));
        showNotification('error', t('mcp.toolCallFailed'));
      } finally {
        setIsCallingTool(false);
      }
    }, 1200);
  };

  const focusMcp = mcpServers.find(s => s.id === focusedMCPServerId);

  // Automatically pre-load tool tester when selecting tools
  const triggerToolTesterPreload = (toolName: string, schema: string) => {
    const defaultVal = toolName === 'read_file'
      ? '{\n  "path": "/workspace/demo.txt"\n}'
      : toolName === 'write_file'
      ? '{\n  "path": "/workspace/demo.txt",\n  "content": "Hello, write sandbox!"\n}'
      : '{\n  "path": "/workspace"\n}';

    setActiveTestTool({ name: toolName, schema });
    setToolTestPayload(defaultVal);
    setToolTestStdout('');
  };

  // Table columns
  const columns = [
    {
      title: t('mcp.mcpName'),
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: MCPServer) => (
        <div className="flex items-center gap-2.5">
          <div
            className="h-9 w-9 rounded-lg flex items-center justify-center shrink-0"
            style={{
              background: record.status === 'connected'
                ? (isDark ? '#162312' : '#f6ffed')
                : (isDark ? '#2a1215' : '#fff2f0'),
              border: `1px solid ${record.status === 'connected'
                ? (isDark ? '#3b6e2f' : '#b7eb8f')
                : (isDark ? '#5c2529' : '#ffccc7')}`,
              color: record.status === 'connected' ? '#52c41a' : '#ff4d4f'
            }}
          >
            <ApiOutlined style={{ fontSize: 16 }} />
          </div>
          <div>
            <div className="font-bold text-sm">{text}</div>
            <Text type="secondary" className="text-xs">{t('mcp.lastHandshake')} {record.lastConnected}</Text>
          </div>
        </div>
      ),
    },
    {
      title: t('mcp.interface'),
      dataIndex: 'connectionType',
      key: 'connectionType',
      width: 100,
      render: (type: string) => <Tag>{type}</Tag>,
    },
    {
      title: t('mcp.descLabel'),
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (text: string) => <Text className="text-xs">{text}</Text>,
    },
    {
      title: t('mcp.statusLabel'),
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: MCPServer['status']) => (
        <Badge
          status={status === 'connected' ? 'success' : status === 'connecting' ? 'processing' : 'error'}
          text={getStatusLabel(status)}
        />
      ),
    },
    {
      title: 'Tools',
      key: 'tools',
      width: 80,
      render: (_: unknown, record: MCPServer) => (
        <Space size={4}>
          <Tooltip title={t('mcp.discoverTools')}>
            <Badge count={record.status === 'connected' ? record.toolsCount : 0} size="small" color="blue">
              <ToolOutlined style={{ fontSize: 14, color: isDark ? '#a6a6a6' : '#595959' }} />
            </Badge>
          </Tooltip>
        </Space>
      ),
    },
    {
      title: t('mcp.actionsLabel'),
      key: 'actions',
      width: 220,
      render: (_: unknown, record: MCPServer) => {
        const isConnected = record.status === 'connected';
        const isConnecting = record.status === 'connecting';
        return (
          <Space size={4}>
            <Button
              size="small"
              danger={isConnected}
              type={isConnected ? 'default' : 'primary'}
              icon={isConnected ? <DisconnectOutlined /> : <LinkOutlined />}
              onClick={() => toggleMCPConnection(record.id)}
              disabled={isConnecting}
              loading={isConnecting}
            >
              {isConnected ? t('mcp.disconnectBtn') : t('mcp.connectBtn')}
            </Button>
            <Tooltip title={t('mcp.refreshSchema')}>
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={() => triggerMCPDiscovery(record.id)}
                disabled={!isConnected}
              />
            </Tooltip>
            <Tooltip title={t('mcp.editConfig')}>
              <Button
                size="small"
                icon={<EditOutlined />}
                onClick={() => handleOpenEdit(record)}
              />
            </Tooltip>
            <Popconfirm
              title={t('mcp.confirmDelete').replace('{name}', record.name)}
              onConfirm={() => deleteMCPServer(record.id)}
              okText={t('common.confirm')}
              cancelText={t('common.cancel')}
            >
              <Tooltip title={t('mcp.removeTooltip')}>
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Tooltip>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  return (
    <div className="px-4 py-6">

      {/* ADD / EDIT MCP CONFIGURE */}
      {editingMCPServerId ? (
        <Card
          className="max-w-2xl mx-auto"
          title={
            <div className="flex items-center gap-2">
              {editingMCPServerId === 'new' ? (
                <>
                  <ApiOutlined className="text-blue-500" />
                  <span>{t('mcp.addMcp')}</span>
                </>
              ) : (
                <>
                  <EditOutlined className="text-blue-500" />
                  <span>{t('mcp.editMcp')}: {formName}</span>
                </>
              )}
            </div>
          }
          extra={
            <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => setEditingMCPServerId(null)}>
              {t('mcp.backToList')}
            </Button>
          }
        >
          <form onSubmit={handleSaveServer} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold mb-1">{t('mcp.idLabel')} <span className="text-red-500">*</span></label>
                <Input
                  required
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder="例如: server-filesystem"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold mb-1">{t('mcp.protocolLabel')}</label>
                <Radio.Group
                  value={formType}
                  onChange={(e) => setFormType(e.target.value)}
                  optionType="button"
                  buttonStyle="solid"
                  size="small"
                  options={[
                    { label: 'STDIO', value: 'STDIO' },
                    { label: 'SSE', value: 'SSE' },
                    { label: 'Streamable HTTP', value: 'Streamable HTTP' },
                  ]}
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold mb-1">{t('mcp.descInputLabel')}</label>
              <Input
                value={formDesc}
                onChange={(e) => setFormDesc(e.target.value)}
                placeholder="例如: 网页自动抓取算力、沙盒文件存取读取模块"
              />
            </div>

            {/* CONNECTIVITY DYNAMIC PANEL SWITCH */}
            {formType === 'STDIO' ? (
              <Card type="inner" size="small" title={t('mcp.stdioConfig')}>
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs mb-1 uppercase" style={{ color: isDark ? '#737373' : '#8c8c8c', fontSize: 10, fontWeight: 'bold' }}>{t('mcp.cmdLabel')}</label>
                    <Input
                      value={formCmd}
                      onChange={(e) => setFormCmd(e.target.value)}
                      placeholder="npx, node, python3"
                    />
                  </div>
                  <div>
                    <label className="block text-xs mb-1 uppercase" style={{ color: isDark ? '#737373' : '#8c8c8c', fontSize: 10, fontWeight: 'bold' }}>{t('mcp.argsLabel')}</label>
                    <Input
                      value={formArgsString}
                      onChange={(e) => setFormArgsString(e.target.value)}
                      placeholder="-y @modelcontextprotocol/server-filesystem /workspace"
                    />
                  </div>
                  <div>
                    <label className="block text-xs mb-1 uppercase" style={{ color: isDark ? '#737373' : '#8c8c8c', fontSize: 10, fontWeight: 'bold' }}>{t('mcp.envLabel')}</label>
                    <TextArea
                      value={formEnvString}
                      onChange={(e) => setFormEnvString(e.target.value)}
                      placeholder="ALLOWED_ROOT=/workspace&#10;DEBUG=mcp:*"
                      rows={2}
                      className="font-mono text-xs"
                    />
                  </div>
                </div>
              </Card>
            ) : (
              <Card type="inner" size="small" title={t('mcp.apiConfig')}>
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs mb-1 uppercase" style={{ color: isDark ? '#737373' : '#8c8c8c', fontSize: 10, fontWeight: 'bold' }}>{t('mcp.urlLabel')}</label>
                    <Input
                      type="url"
                      required={formType !== 'STDIO'}
                      value={formUrl}
                      onChange={(e) => setFormUrl(e.target.value)}
                      placeholder="http://localhost:8080/mcp/sse"
                    />
                  </div>
                  <div>
                    <label className="block text-xs mb-1 uppercase" style={{ color: isDark ? '#737373' : '#8c8c8c', fontSize: 10, fontWeight: 'bold' }}>{t('mcp.headersLabel')}</label>
                    <TextArea
                      value={formHeadersString}
                      onChange={(e) => setFormHeadersString(e.target.value)}
                      placeholder="Authorization=Bearer mcp-auth-token-xxx"
                      rows={2}
                      className="font-mono text-xs"
                    />
                  </div>
                </div>
              </Card>
            )}

            {/* Global configurations */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 p-4 rounded-lg border" style={{
              borderColor: isDark ? '#303030' : '#f0f0f0',
              background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.01)'
            }}>
              <div>
                <label className="block text-xs font-semibold mb-1">{t('mcp.timeoutLabel')}</label>
                <Input
                  type="number"
                  value={formTimeout}
                  onChange={(e) => setFormTimeout(Number(e.target.value))}
                />
              </div>
              <div className="flex items-center gap-1.5 pt-5 select-none h-full">
                <input
                  type="checkbox"
                  checked={formReconnect}
                  onChange={(e) => setFormReconnect(e.target.checked)}
                />
                <label className="text-xs cursor-pointer">{t('mcp.reconnectLabel')}</label>
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">{t('mcp.retriesLabel')}</label>
                <Input
                  type="number"
                  disabled={!formReconnect}
                  value={formMaxRetries}
                  onChange={(e) => setFormMaxRetries(Number(e.target.value))}
                />
              </div>
            </div>

            <div className="flex gap-2 justify-end pt-4 border-t" style={{ borderColor: isDark ? '#303030' : '#f0f0f0' }}>
              <Button onClick={() => setEditingMCPServerId(null)}>{t('common.cancel')}</Button>
              <Button type="primary" htmlType="submit">{t('mcp.saveMcp')}</Button>
            </div>
          </form>
        </Card>
      ) : (
        <div className="space-y-6">
          <Card size="small">
            {/* Toolbar */}
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <Input
                prefix={<SearchOutlined />}
                placeholder={t('mcp.searchPlaceholder')}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ width: 200 }}
                allowClear
              />
              <Button
                id="btn-add-mcp"
                type="primary"
                icon={<PlusOutlined />}
                onClick={handleOpenCreate}
              >
                MCP Server
              </Button>
            </div>

            {/* Table listing */}
            <Table
              dataSource={filteredServers.map(srv => ({ ...srv, key: srv.id }))}
              columns={columns}
              pagination={false}
              size="middle"
              onRow={(record) => ({
                onClick: () => {
                  if (focusedMCPServerId === record.id) {
                    setFocusedMCPServerId(null);
                  } else {
                    setFocusedMCPServerId(record.id);
                  }
                },
                style: { cursor: 'pointer' },
              })}
              rowClassName={(record) =>
                focusedMCPServerId === record.id ? 'ant-table-row-selected' : ''
              }
              locale={{ emptyText: <Empty description={t('mcp.noMcp')} /> }}
            />
          </Card>

          {/* DETAILED RUNS AND CONSOLE LOGS */}
          {focusMcp && (
            <ResizableModal
              open={!!focusMcp}
              onCancel={() => setFocusedMCPServerId(null)}
              width={1000}
              title={
                <div className="flex items-center gap-2">
                  <ApiOutlined style={{ color: '#1677ff' }} />
                  <span className="font-bold">{focusMcp.name} {t('mcp.detailPanel')}</span>
                  <Badge
                    status={focusMcp.status === 'connected' ? 'success' : focusMcp.status === 'connecting' ? 'processing' : 'error'}
                    text={getStatusLabel(focusMcp.status)}
                  />
                </div>
              }
              footer={
                <Space>
                  <Button
                    size="small"
                    danger={focusMcp.status === 'connected'}
                    type={focusMcp.status === 'connected' ? 'default' : 'primary'}
                    onClick={() => toggleMCPConnection(focusMcp.id)}
                  >
                    {focusMcp.status === 'connected' ? t('mcp.disconnectProcess') : t('mcp.startConnect')}
                  </Button>
                  <Button
                    size="small"
                    icon={<ReloadOutlined />}
                    onClick={() => triggerMCPDiscovery(focusMcp.id)}
                    disabled={focusMcp.status !== 'connected'}
                  >
                    {t('mcp.refreshDiscovery')}
                  </Button>
                  <Button onClick={() => setFocusedMCPServerId(null)}>{t('mcp.closeLabel')}</Button>
                </Space>
              }
              draggable
              resizable
            >
              <Paragraph type="secondary" className="mb-4">{focusMcp.description}</Paragraph>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

                {/* Left side: logs and config */}
                <div className="space-y-4">
                  {/* Log terminal */}
                  <Card
                    type="inner"
                    size="small"
                    title={
                      <span className="font-mono tracking-wider flex items-center gap-1.5">
                        <Terminal style={{ width: 14, height: 14, color: '#eb2f96' }} />
                        STDERR {t('mcp.stderrLog')}
                      </span>
                    }
                    style={{
                      background: isDark ? '#141414' : '#1f1f1f',
                      borderColor: isDark ? '#303030' : '#303030'
                    }}
                    headStyle={{
                      background: isDark ? '#1f1f1f' : '#1f1f1f',
                      color: '#a6a6a6',
                      borderBottomColor: '#303030'
                    }}
                    bodyStyle={{ background: isDark ? '#141414' : '#141414', color: '#8c8c8c' }}
                  >
                    <Timeline
                      items={focusMcp.logs.map((lg) => ({
                        color: 'gray',
                        children: (
                          <div className="font-mono text-xs leading-relaxed">
                            <span style={{ color: '#595959' }}>[{lg.time}]</span>{' '}
                            <span style={{ color: '#eb2f96' }}>[{lg.fromStatus} ➔ {lg.toStatus}]</span>{' '}
                            <span style={{ color: '#a6a6a6' }}>{lg.message}</span>
                          </div>
                        ),
                      }))}
                    />
                    <div className="border-t pt-1.5 text-right font-mono" style={{ borderColor: '#303030', color: '#595959', fontSize: 10 }}>
                      SHELL STATUS: STABLE TRACE ACTIVE
                    </div>
                  </Card>

                  {/* Config details */}
                  <Card type="inner" size="small" title={t('mcp.configDetail')}>
                    {focusMcp.connectionType === 'STDIO' ? (
                      <Descriptions column={1} size="small" className="text-xs">
                        <Descriptions.Item label="Command">
                          <Tag>{focusMcp.config.command}</Tag>
                        </Descriptions.Item>
                        <Descriptions.Item label="Args">
                          <code className="text-xs px-1 py-0.5 rounded" style={{ background: isDark ? '#262626' : '#fafafa' }}>
                            {focusMcp.config.args?.join(' ')}
                          </code>
                        </Descriptions.Item>
                        <Descriptions.Item label="Envs">
                          <code className="text-xs px-1 py-0.5 rounded" style={{ background: isDark ? '#262626' : '#fafafa' }}>
                            {focusMcp.config.env?.map(e => `${e.key}=${e.value}`).join(', ')}
                          </code>
                        </Descriptions.Item>
                      </Descriptions>
                    ) : (
                      <Descriptions column={1} size="small">
                        <Descriptions.Item label="Endpoint">
                          <code className="text-xs px-1 py-0.5 rounded break-all" style={{ background: isDark ? '#262626' : '#fafafa' }}>
                            {focusMcp.config.url}
                          </code>
                        </Descriptions.Item>
                        <Descriptions.Item label="Headers">
                          <code className="text-xs px-1 py-0.5 rounded" style={{ background: isDark ? '#262626' : '#fafafa' }}>
                            {focusMcp.config.headers?.map(h => `${h.key}=***`).join(', ')}
                          </code>
                        </Descriptions.Item>
                      </Descriptions>
                    )}
                  </Card>
                </div>

                {/* Right side: tools */}
                <div className="space-y-4">

                  <Card type="inner" size="small" title={`${t('mcp.discoveredTools')} (${focusMcp.status === 'connected' ? focusMcp.tools.length : 0}${t('mcp.activeCount')})`}>
                    {focusMcp.status !== 'connected' ? (
                      <Empty
                        description={t('mcp.noConnection')}
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                      />
                    ) : focusMcp.tools.length === 0 ? (
                      <Empty description={t('mcp.noTools')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    ) : (
                      <div className="space-y-2 max-h-[170px] overflow-y-auto">
                        {focusMcp.tools.map((tl, index) => (
                          <div key={index} className="p-3 rounded border flex items-start justify-between gap-4" style={{ background: isDark ? '#141414' : '#fafafa', borderColor: isDark ? '#303030' : '#f0f0f0' }}>
                            <div>
                              <div className="font-mono font-bold text-xs">{tl.name}</div>
                              <div className="text-xs mt-1" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>{tl.description}</div>
                            </div>
                            <Button
                              type="link"
                              size="small"
                              icon={<PlayCircleOutlined />}
                              onClick={() => triggerToolTesterPreload(tl.name, tl.schema)}
                            >
                              {t('mcp.testCall')}
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </Card>

                  {/* Active Tool Interactive Tester Block */}
                  {activeTestTool && focusMcp.status === 'connected' && (
                    <Card
                      type="inner"
                      size="small"
                      style={{
                        background: isDark ? '#141414' : '#1f1f1f',
                        borderColor: isDark ? '#303030' : '#303030'
                      }}
                      headStyle={{
                        background: isDark ? '#1f1f1f' : '#1f1f1f',
                        color: isDark ? '#e8e8e8' : '#e8e8e8',
                        borderBottomColor: '#303030'
                      }}
                      bodyStyle={{ background: isDark ? '#141414' : '#141414' }}
                      title={
                        <span style={{ color: '#59b9ff' }} className="flex items-center gap-1">
                          <ToolOutlined /> {t('mcp.reverseDebugger')}: {activeTestTool.name}
                        </span>
                      }
                      extra={
                        <Button type="text" size="small" onClick={() => setActiveTestTool(null)} style={{ color: '#595959' }}>
                          x
                        </Button>
                      }
                    >
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                          <label className="block text-xs mb-1" style={{ color: '#737373', fontSize: 10, fontWeight: 'bold' }}>{t('mcp.testPayload')}</label>
                          <TextArea
                            value={toolTestPayload}
                            onChange={(e) => setToolTestPayload(e.target.value)}
                            rows={4}
                            className="font-mono text-xs"
                            style={{ background: isDark ? '#0d0d0d' : '#0d0d0d', color: '#e8e8e8' }}
                          />
                          <Button
                            type="primary"
                            block
                            className="mt-2"
                            icon={isCallingTool ? <LoadingOutlined /> : <PlayCircleOutlined />}
                            onClick={() => runToolExecutionTrial(activeTestTool.name)}
                            disabled={isCallingTool}
                            size="small"
                          >
                            {isCallingTool ? t('mcp.parsing') : t('mcp.testCallApi')}
                          </Button>
                        </div>
                        <div className="font-mono text-xs flex flex-col" style={{ background: isDark ? '#0d0d0d' : '#0d0d0d', borderRadius: 6, padding: 10, maxHeight: 140, overflow: 'auto' }}>
                          <span className="uppercase tracking-wider mb-1" style={{ color: '#595959', fontSize: 10, fontWeight: 'bold' }}>{t('mcp.stdoutResponse')}</span>
                          <pre style={{ color: '#52c41a', whiteSpace: 'pre-wrap', fontSize: 9.5 }}>{toolTestStdout || t('mcp.noRequest')}</pre>
                        </div>
                      </div>
                    </Card>
                  )}

                </div>

              </div>
            </ResizableModal>
          )}

        </div>
      )}

    </div>
  );
};
