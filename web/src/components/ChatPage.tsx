import React, { useState, useEffect, useRef } from 'react';
import { useAppState } from '../AppContext';
import { Chat, Message, Agent, Task } from '../types';
import { useTheme } from '../ThemeContext';
import {
  Send, Bot, User, Cpu, Play, Search, FolderPlus, Clock, ChevronDown,
  ChevronUp, ChevronRight, HelpCircle, AlertCircle, Sparkles, Plus,
  Archive, Download, ArrowRight, CornerDownRight, Check, XCircle
} from 'lucide-react';
import { useTranslation } from '../LocaleContext';
import {
  Input, Button, List, Avatar, Card, Tag, Space, Typography, Tooltip,
  Collapse, Progress, Badge, Divider, Empty, Select, Popconfirm, message
} from 'antd';
import {
  SendOutlined, RobotOutlined, UserOutlined, PlusOutlined,
  MessageOutlined, SearchOutlined, ClockCircleOutlined,
  ThunderboltOutlined, DownloadOutlined, RightOutlined,
  CheckCircleOutlined, CloseCircleOutlined, CodeOutlined,
  LoadingOutlined
} from '@ant-design/icons';

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;

export const ChatPage: React.FC = () => {
  const {
    chats,
    agents,
    tasks,
    currentChatId,
    setCurrentChatId,
    sendChatMessage,
    addChat,
    deleteChat,
    convertMessageToTask,
    triggerAgentTaskSuggestion,
    delegateChatExecutionToBackground,
    setActiveTab,
    setFocusedTaskId,
    showNotification
  } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();

  const [inputVal, setInputVal] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [searchSidebar, setSearchSidebar] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // States to toggle tool call detail open/closed
  const [expandedToolCalls, setExpandedToolCalls] = useState<Record<string, boolean>>({});

  // Form state to trigger manually convert to task Drawer
  const [taskDrawerMsg, setTaskDrawerMsg] = useState<Message | null>(null);
  const [taskDrawerTitle, setTaskDrawerTitle] = useState('');
  const [taskDrawerPriority, setTaskDrawerPriority] = useState<Task['priority']>('high');

  // Trigger scroll to bottom on new messages
  const activeChat = chats.find(c => c.id === currentChatId);
  const messages = activeChat?.messages || [];
  const activeAgent = activeChat ? agents.find(a => a.id === activeChat.agentId) : null;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputVal.trim() || !currentChatId) return;

    sendChatMessage(currentChatId, inputVal.trim());
    setInputVal('');
  };

  const toggleToolCallCode = (tcId: string) => {
    setExpandedToolCalls(prev => ({
      ...prev,
      [tcId]: !prev[tcId]
    }));
  };

  const handleOpenTaskConvertDrawer = (msg: Message) => {
    setTaskDrawerMsg(msg);
    setTaskDrawerTitle(msg.text.length > 20 ? msg.text.substring(0, 18) + '...' : msg.text);
    setTaskDrawerPriority('high');
  };

  const handleExecuteTaskDrawer = () => {
    if (!taskDrawerMsg || !currentChatId) return;

    const taskObj = convertMessageToTask(
      currentChatId,
      taskDrawerMsg.id,
      taskDrawerTitle,
      taskDrawerPriority
    );
    setFocusedTaskId(taskObj.id);
    setTaskDrawerMsg(null);
  };

  const getPriorityBadgeColor = (p: Task['priority']): string => {
    switch (p) {
      case 'urgent': return 'red';
      case 'high': return 'orange';
      case 'medium': return 'gold';
      case 'low': return 'green';
    }
  };

  const getPriorityLabel = (p: Task['priority']) => {
    switch (p) {
      case 'urgent': return t('chat.urgent');
      case 'high': return t('chat.high');
      case 'medium': return t('chat.medium');
      case 'low': return t('chat.low');
    }
  };

  // Group sidebars chats by date
  const filteredChats = chats.filter(c => {
    const ag = agents.find(a => a.id === c.agentId);
    return c.title.toLowerCase().includes(searchSidebar.toLowerCase()) ||
           ag?.name.toLowerCase().includes(searchSidebar.toLowerCase());
  });

  const todayChats = filteredChats;

  return (
    <div className="h-full flex items-stretch relative overflow-hidden">

      {/* SIDEBAR DIALOG LIST */}
      <div
        className={`border-r w-[260px] flex flex-col justify-between transition-all duration-300 z-10 shrink-0 ${
          sidebarOpen ? 'ml-0' : 'ml-[-260px]'
        }`}
        style={{
          background: isDark ? '#1f1f1f' : '#ffffff',
          borderColor: isDark ? '#303030' : '#f0f0f0'
        }}
        id="chat-sidebar"
      >
        <div className="flex-1 flex flex-col min-h-0">
          <div className="p-3 border-b space-y-2" style={{ borderColor: isDark ? '#303030' : '#f0f0f0' }}>
            <div className="text-xs font-bold uppercase tracking-widest" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>
              {t('chat.chatHistory')}
            </div>
            <Input
              prefix={<SearchOutlined />}
              size="small"
              value={searchSidebar}
              onChange={(e) => setSearchSidebar(e.target.value)}
              placeholder={t('chat.searchPlaceholder')}
            />
          </div>

          {/* List grouped */}
          <div className="flex-1 overflow-y-auto p-2 space-y-3">
            <div className="space-y-1">
              <div className="text-xs font-bold px-2 tracking-wider uppercase mb-1" style={{ color: isDark ? '#737373' : '#8c8c8c', fontSize: 10 }}>
                {t('chat.today')}
              </div>
              {todayChats.length === 0 ? (
                <div className="text-xs italic px-2" style={{ color: isDark ? '#595959' : '#bfbfbf' }}>{t('chat.noHistory')}</div>
              ) : (
                todayChats.map(c => {
                  const ag = agents.find(a => a.id === c.agentId);
                  const isCurrent = c.id === currentChatId;
                  return (
                    <div
                      key={c.id}
                      onClick={() => setCurrentChatId(c.id)}
                      className={`group relative flex flex-col gap-0.5 rounded-lg p-2.5 cursor-pointer text-left transition select-none ${
                        isCurrent
                          ? (isDark ? 'bg-blue-900/30 border border-blue-800' : 'bg-blue-50 border border-blue-100')
                          : (isDark ? 'hover:bg-gray-800' : 'hover:bg-slate-50')
                      }`}
                    >
                      <div className="font-semibold text-xs line-clamp-1 pr-6">{c.title}</div>
                      <div className="flex items-center gap-1.5 mt-0.5" style={{ color: isDark ? '#595959' : '#8c8c8c', fontSize: 9 }}>
                        <span className="flex items-center gap-0.5">
                          <RobotOutlined style={{ fontSize: 10 }} />
                          {ag?.name || t('chat.unknownBot')}
                        </span>
                        <span>|</span>
                        <span>{c.messages.length}{t('chat.messages')}</span>
                      </div>

                      <Popconfirm
                        title={t('chat.confirmDeleteChat')}
                        onConfirm={() => deleteChat(c.id)}
                        okText={t('common.confirm')}
                        cancelText={t('common.cancel')}
                      >
                        <Button
                          type="text"
                          size="small"
                          danger
                          className="absolute right-1 top-1.5 opacity-0 group-hover:opacity-100"
                          style={{ fontSize: 10 }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          x
                        </Button>
                      </Popconfirm>
                    </div>
                  );
                })
              )}
            </div>

            <div className="space-y-1">
              <div className="text-xs font-bold px-2 tracking-wider uppercase mb-1" style={{ color: isDark ? '#737373' : '#8c8c8c', fontSize: 10 }}>
                {t('chat.earlierHistory')}
              </div>
              <div className="rounded p-2 text-xs italic px-2" style={{ color: isDark ? '#595959' : '#bfbfbf' }}>
                {t('chat.noArchive')}
              </div>
            </div>
          </div>
        </div>

        {/* Create new Chat button inside sidebar */}
        <div className="p-3 border-t" style={{ borderColor: isDark ? '#303030' : '#f0f0f0', background: isDark ? '#141414' : '#fafafa' }}>
          <div className="text-xs font-bold mb-1.5 px-0.5" style={{ color: isDark ? '#737373' : '#8c8c8c' }}>{t('chat.quickChannel')}</div>
          <div className="grid grid-cols-1 gap-1">
            {agents.filter(a => a.status === 'published').map(a => (
              <Button
                key={a.id}
                size="small"
                block
                icon={<MessageOutlined />}
                onClick={() => addChat(a.id)}
                className="text-left flex items-center justify-between"
              >
                <span className="truncate">{t('chat.chatWith')} {a.name}</span>
              </Button>
            ))}
          </div>
        </div>
      </div>

      {/* Toggler arrow strip floating */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="absolute left-0 top-1/2 translate-y-[-50%] w-4 h-16 rounded-r-md flex items-center justify-center shadow-sm z-20 shrink-0 cursor-pointer"
        style={{
          background: isDark ? '#1f1f1f' : '#ffffff',
          border: `1px solid ${isDark ? '#303030' : '#f0f0f0'}`,
          borderLeft: 'none',
          color: isDark ? '#737373' : '#8c8c8c'
        }}
        title={sidebarOpen ? t('chat.collapseSidebar') : t('chat.expandSidebar')}
      >
        <span className="text-xs font-bold leading-none">{sidebarOpen ? '<' : '>'}</span>
      </button>

      {/* MAIN CONVERSATION PANEL */}
      <div className="flex-1 flex flex-col justify-between min-w-0 relative" style={{ background: isDark ? '#141414' : '#f5f5f5' }}>
        {activeChat ? (
          <>
            {/* Chat info bar */}
            <div className="px-4 py-2.5 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2">
                <Avatar
                  size={32}
                  icon={<RobotOutlined />}
                  style={{ backgroundColor: isDark ? '#1d3962' : '#e6f4ff', color: '#1677ff' }}
                />
                <div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-xs">{activeChat.title}</span>
                    <Badge status="processing" color="#52c41a" />
                    <span className="text-xs" style={{ color: isDark ? '#595959' : '#8c8c8c', fontSize: 9.5 }}>
                      ({activeAgent?.name || t('chat.unknownAgent')})
                    </span>
                  </div>
                  <div className="text-xs" style={{ color: isDark ? '#595959' : '#8c8c8c', fontSize: 9.5 }}>
                    {t('chat.agentInfo').replace('{skills}', String(activeAgent?.skills.length || 0)).replace('{mcp}', String(activeAgent?.mcpServers.length || 0))}
                  </div>
                </div>
              </div>

              <Space>
                <Button
                  size="small"
                  icon={<ThunderboltOutlined />}
                  onClick={() => triggerAgentTaskSuggestion(currentChatId!)}
                >
                  {t('chat.triggerTaskSuggestion')}
                </Button>
                <Button
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={() => addChat(activeChat.agentId)}
                >
                  {t('chat.newChat')}
                </Button>
              </Space>
            </div>

            {/* MESSAGE CONTAINER */}
            <div className="flex-1 overflow-y-auto p-4 space-y-6">
              {messages.map((msg, index) => {
                const isUser = msg.sender === 'user';
                const isSystem = msg.sender === 'system';

                if (isSystem) {
                  return (
                    <div key={msg.id} className="mx-auto max-w-xl text-center space-y-2.5 py-1">
                      <div className="text-xs flex items-center justify-center gap-1.5 select-none" style={{ color: isDark ? '#595959' : '#8c8c8c' }}>
                        <span className="h-1.5 w-8 rounded-full" style={{ background: isDark ? '#303030' : '#e8e8e8' }} />
                        <span>{msg.text}</span>
                        <span className="h-1.5 w-8 rounded-full" style={{ background: isDark ? '#303030' : '#e8e8e8' }} />
                      </div>

                      {/* Task card */}
                      {msg.taskCard && (
                        <Card
                          size="small"
                          className="text-left"
                          style={{ background: isDark ? '#1f1f1f' : '#ffffff', borderColor: isDark ? '#303030' : '#f0f0f0' }}
                        >
                          <div className="flex justify-between items-start gap-4 mb-2 pb-2 border-b" style={{ borderColor: isDark ? '#303030' : '#f0f0f0' }}>
                            <div>
                              <div className="font-mono uppercase tracking-wider text-xs" style={{ color: isDark ? '#595959' : '#8c8c8c', fontSize: 10 }}>{t('chat.syncTaskNode')}</div>
                              <Title level={5} style={{ margin: '4px 0 0', color: isDark ? '#e8e8e8' : '#262626' }}>{msg.taskCard.title}</Title>
                            </div>
                            <Tag color={getPriorityBadgeColor(msg.taskCard.priority)}>{getPriorityLabel(msg.taskCard.priority)}</Tag>
                          </div>

                          <div className="flex justify-between items-center text-xs mb-1.5 font-mono">
                            <span className="flex items-center gap-1">
                              {msg.taskCard.status === 'completed' ? (
                                <Badge status="success" />
                              ) : (
                                <Badge status="processing" />
                              )}
                              <span>{t('chat.statusLabel')} {msg.taskCard.status === 'completed' ? t('chat.completed') : t('chat.asyncRunning')}</span>
                            </span>
                            <span className="font-bold">{msg.taskCard.progress}%</span>
                          </div>

                          <Progress
                            percent={msg.taskCard.progress}
                            size="small"
                            strokeColor={msg.taskCard.status === 'completed' ? '#52c41a' : '#1677ff'}
                            showInfo={false}
                          />

                          {msg.taskCard.subtasks && msg.taskCard.subtasks.length > 0 && (
                            <div className="space-y-1.5 border-t pt-3 mt-3" style={{ borderColor: isDark ? '#303030' : '#f0f0f0' }}>
                              {msg.taskCard.subtasks.slice(0, 3).map((sub, sIdx) => (
                                <div key={sIdx} className="flex items-center justify-between text-xs">
                                  <div className="flex items-center gap-2">
                                    <Badge status={sub.status === 'completed' ? 'success' : 'processing'} />
                                    <span>{sub.title}</span>
                                  </div>
                                  <span className="font-mono" style={{ color: isDark ? '#595959' : '#8c8c8c', fontSize: 10 }}>
                                    {sub.status === 'completed' ? t('chat.completedShort') : t('chat.runningShort')}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}

                          {msg.taskCard.resultSummary && (
                            <div className="mt-3 p-3 rounded-lg border" style={{ borderColor: isDark ? '#303030' : '#f0f0f0', background: isDark ? '#141414' : '#fafafa' }}>
                              <span className="font-bold flex items-center gap-1.5 mb-1">{t('chat.runSummary')}</span>
                              <div className="text-xs leading-relaxed" style={{ color: isDark ? '#a6a6a6' : '#595959' }}>{msg.taskCard.resultSummary}</div>
                              <Button
                                size="small"
                                type="primary"
                                icon={<DownloadOutlined />}
                                className="mt-2"
                                onClick={() => showNotification('success', t('chat.downloading'))}
                              >
                                {t('chat.downloadResult')}
                              </Button>
                            </div>
                          )}

                          <div className="mt-3 pt-2 border-t flex justify-end" style={{ borderColor: isDark ? '#303030' : '#f0f0f0' }}>
                            <Button
                              type="link"
                              size="small"
                              onClick={() => {
                                setFocusedTaskId(msg.taskCard!.taskId);
                                setActiveTab('tasks');
                              }}
                            >
                              {t('chat.openTaskDetail')}
                            </Button>
                          </div>
                        </Card>
                      )}
                    </div>
                  );
                }

                // Standard Message Bubbles
                return (
                  <div
                    key={msg.id}
                    id={`msg-bubble-${msg.id}`}
                    className={`flex items-start gap-3 max-w-2xl group relative ${
                      isUser ? 'ml-auto flex-row-reverse' : 'mr-auto text-left'
                    }`}
                  >
                    <Avatar
                      size={32}
                      icon={isUser ? <UserOutlined /> : <RobotOutlined />}
                      style={{
                        backgroundColor: isUser ? '#1677ff' : (isDark ? '#303030' : '#ffffff'),
                        color: isUser ? '#ffffff' : (isDark ? '#e8e8e8' : '#595959'),
                        border: isUser ? 'none' : `1px solid ${isDark ? '#434343' : '#f0f0f0'}`
                      }}
                    />

                    <div className="space-y-2">
                      <div
                        className="rounded-2xl p-3.5 text-xs leading-relaxed border"
                        style={{
                          background: isUser ? '#1677ff' : (isDark ? '#1f1f1f' : '#ffffff'),
                          color: isUser ? '#ffffff' : (isDark ? '#e8e8e8' : '#262626'),
                          borderColor: isUser ? '#1677ff' : (isDark ? '#303030' : '#f0f0f0'),
                          borderTopRightRadius: isUser ? 4 : undefined,
                          borderTopLeftRadius: !isUser ? 4 : undefined,
                        }}
                      >
                        <div className="whitespace-pre-wrap">{msg.text}</div>

                        {/* Rendering simulated progressive cursor */}
                        {!isUser && msg.text.endsWith('▍') && (
                          <span className="inline-block h-3.5 w-[3px] ml-1 select-none animate-ping" style={{ background: isDark ? '#595959' : '#8c8c8c' }} />
                        )}

                        {/* TOOL CALL EVENT */}
                        {msg.toolCalls && msg.toolCalls.map(tc => {
                          const isSuccess = tc.status === 'success';
                          const isRunning = tc.status === 'running';
                          const isExpanded = expandedToolCalls[tc.id] || false;

                          return (
                            <div key={tc.id} className="mt-3 border rounded-lg overflow-hidden" style={{
                              background: isDark ? '#141414' : '#fafafa',
                              borderColor: isDark ? '#303030' : '#f0f0f0'
                            }}>
                              <div
                                onClick={() => toggleToolCallCode(tc.id)}
                                className="px-3 py-2 flex items-center justify-between text-xs font-semibold font-mono cursor-pointer select-none border-b"
                                style={{
                                  background: isDark ? '#262626' : '#f5f5f5',
                                  borderColor: isDark ? '#303030' : '#f0f0f0',
                                  color: isDark ? '#a6a6a6' : '#595959'
                                }}
                              >
                                <span className="flex items-center gap-1.5">
                                  {isRunning && <LoadingOutlined spin />}
                                  {isSuccess && <CheckCircleOutlined style={{ color: '#52c41a' }} />}
                                  <span>{t('chat.callTool')} {tc.name}</span>
                                </span>
                                <div className="flex items-center gap-1.5 font-sans font-normal">
                                  <span>{isRunning ? t('chat.fastFeedback') : `${t('chat.duration')} ${tc.duration || '0.8'}s`}</span>
                                  {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                                </div>
                              </div>

                              {isExpanded && (
                                <div className="p-2.5 font-mono text-xs leading-relaxed max-h-[160px] overflow-y-auto" style={{ background: isDark ? '#141414' : '#1f1f1f', color: isDark ? '#d9d9d9' : '#d9d9d9' }}>
                                  <div style={{ color: '#59b9ff' }} className="font-bold mb-1">{t('chat.passParams')}</div>
                                  <pre className="whitespace-pre" style={{ color: '#e8e8e8' }}>{tc.args}</pre>

                                  {tc.result && (
                                    <>
                                      <div style={{ color: '#73d13d' }} className="font-bold mt-2.5 mb-1">{t('chat.toolResponse')}</div>
                                      <pre className="whitespace-pre" style={{ color: '#a6a6a6' }}>{tc.result}</pre>
                                    </>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}

                        {/* Suggestion card */}
                        {msg.suggestionCard && (
                          <div className="mt-4 p-3 rounded-lg space-y-2.5" style={{
                            background: isDark ? '#111d2c' : '#f0f5ff',
                            borderColor: isDark ? '#15325b' : '#d6e4ff',
                            border: `1px solid ${isDark ? '#15325b' : '#d6e4ff'}`
                          }}>
                            <div className="flex items-center gap-2">
                              <ThunderboltOutlined style={{ color: '#1677ff' }} />
                              <span className="font-bold text-xs" style={{ color: isDark ? '#e8e8e8' : '#262626' }}>{t('chat.agentSuggestion')}</span>
                            </div>
                            <div className="text-xs leading-relaxed" style={{ color: isDark ? '#a6a6a6' : '#595959' }}>
                            {t('chat.complexSteps')} <b>{msg.suggestionCard.stepsCount} {t('chat.stepsUnit')}</b> {t('chat.complexModule')}
                              {t('chat.estimatedDuration')} <b>{msg.suggestionCard.eta}</b>。{t('chat.convertToTask')}
                            </div>
                            <div className="flex items-center gap-2 pt-1">
                              <Button
                                type="primary"
                                size="small"
                                onClick={() => handleOpenTaskConvertDrawer(msg)}
                              >
                                {t('chat.createAndExecute')}
                              </Button>
                              <Button
                                type="text"
                                size="small"
                                onClick={() => showNotification('warning', t('chat.ignored'))}
                                style={{ color: isDark ? '#a6a6a6' : '#595959' }}
                              >
                                {t('chat.ignoreSuggestion')}
                              </Button>
                            </div>
                          </div>
                        )}

                        {/* Delegation prompt box */}
                        {msg.delegationTip && (
                          <div className="mt-3 p-2.5 rounded border text-xs" style={{
                            background: isDark ? '#1f1f1f' : '#fafafa',
                            borderColor: isDark ? '#303030' : '#f0f0f0',
                            color: isDark ? '#a6a6a6' : '#595959'
                          }}>
                            <span className="font-semibold flex items-center gap-1" style={{ color: isDark ? '#e8e8e8' : '#262626' }}>
                              <ClockCircleOutlined /> {t('chat.delegatedToBackend')}
                            </span>
                            {t('chat.delegationDesc')}
                          </div>
                        )}
                      </div>

                      {/* Floating actions on hover for user messages */}
                      {isUser && (
                        <div className="opacity-0 group-hover:opacity-100 absolute left-[-100px] top-[14px] flex items-center gap-1.5 transition">
                          <Tooltip title={t('chat.convertToTaskTooltip')}>
                            <Button
                              size="small"
                              icon={<FolderPlus className="h-3 w-3" />}
                              onClick={() => handleOpenTaskConvertDrawer(msg)}
                            >
                              {t('chat.convertToTaskBtn')}
                            </Button>
                          </Tooltip>
                        </div>
                      )}

                      <div className="text-xs select-none text-right" style={{ color: isDark ? '#595959' : '#bfbfbf', fontSize: 9.5 }}>
                        {msg.timestamp}
                      </div>
                    </div>
                  </div>
                );
              })}
              <div ref={messagesEndRef} />
            </div>

            {/* SEND BOTTOM CONTAINER */}
            <form onSubmit={handleSend} className="p-3 border-t flex gap-2 items-center text-xs shrink-0" style={{
              background: isDark ? '#1f1f1f' : '#ffffff',
              borderColor: isDark ? '#303030' : '#f0f0f0'
            }}>
              <Input
                value={inputVal}
                onChange={(e) => setInputVal(e.target.value)}
                placeholder={`${t('chat.inputPrefix')}「${activeAgent?.name || t('chat.unknownBot')}」${t('chat.inputPlaceholder')}`}
                size="large"
              />
              <Button
                type="primary"
                htmlType="submit"
                id="btn-chat-send"
                size="large"
                icon={<SendOutlined />}
              >
                {t('chat.send')}
              </Button>
            </form>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center m-6 rounded-xl p-12 text-center">
            <RobotOutlined style={{ fontSize: 48, color: isDark ? '#595959' : '#bfbfbf' }} />
            <Title level={5} className="mt-4">{t('chat.startNewChat')}</Title>
            <Paragraph type="secondary" className="max-w-sm">
              {t('chat.selectAgent')}
            </Paragraph>
            <div className="mt-6 flex flex-wrap gap-2.5 justify-center max-w-lg">
              {agents.filter(a => a.status === 'published').map(a => (
                <Button
                  key={a.id}
                  icon={<RightOutlined />}
                  onClick={() => addChat(a.id)}
                >
                  {t('chat.chatWithAgent').replace('{name}', a.name)}
                </Button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* SLIDING CONVERSION TASK DRAWER PANEL */}
      {taskDrawerMsg && (
        <div className="fixed inset-0 z-50 flex justify-end" style={{ background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(2px)' }}>
          <div
            onClick={() => setTaskDrawerMsg(null)}
            className="absolute inset-0"
          />
          <div className="relative bg-white dark:bg-gray-900 w-full max-w-md h-full shadow-2xl flex flex-col justify-between border-l py-6 px-5 transition-transform" style={{
            background: isDark ? '#1f1f1f' : '#ffffff',
            borderColor: isDark ? '#303030' : '#f0f0f0'
          }}>
            <div className="space-y-6">
              <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: isDark ? '#303030' : '#f0f0f0' }}>
                <div className="flex items-center gap-2">
                  <ClockCircleOutlined style={{ color: '#1677ff', fontSize: 18 }} />
                  <Title level={5} style={{ margin: 0 }}>{t('chat.createTaskNode')}</Title>
                </div>
                <Button type="text" onClick={() => setTaskDrawerMsg(null)}>x</Button>
              </div>

              <div>
                <label className="block text-xs font-bold uppercase mb-1" style={{ color: isDark ? '#737373' : '#8c8c8c', fontSize: 10 }}>{t('chat.messageSource')}</label>
                <div className="p-3 rounded-lg border text-xs leading-relaxed italic" style={{
                  background: isDark ? '#141414' : '#fafafa',
                  borderColor: isDark ? '#303030' : '#f0f0f0',
                  color: isDark ? '#a6a6a6' : '#595959'
                }}>
                  "{taskDrawerMsg.text}"
                </div>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold mb-1.5">{t('chat.taskTitle')} <span className="text-red-500">*</span></label>
                  <Input
                    value={taskDrawerTitle}
                    onChange={(e) => setTaskDrawerTitle(e.target.value)}
                    placeholder={t('chat.taskTitlePlaceholder')}
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold mb-1.5">{t('chat.agentGateway')}</label>
                  <div className="p-3 rounded-lg border flex items-center gap-2.5 select-none" style={{
                    background: isDark ? '#141414' : '#fafafa',
                    borderColor: isDark ? '#303030' : '#f0f0f0'
                  }}>
                    <Avatar size={32} icon={<RobotOutlined />} style={{ backgroundColor: isDark ? '#1d3962' : '#e6f4ff', color: '#1677ff' }} />
                    <div>
                      <div className="text-xs font-bold">{activeAgent?.name || t('chat.unknownAgent')}</div>
                      <div className="text-xs" style={{ color: isDark ? '#737373' : '#8c8c8c', fontSize: 10 }}>
                        {activeAgent?.type === 'hybrid' ? t('chat.hybridType') : t('chat.chatServiceType')} | {activeAgent?.skills.length} Skills
                      </div>
                    </div>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold mb-1.5">{t('chat.priorityLabel')}</label>
                  <Space>
                    {(['low', 'medium', 'high', 'urgent'] as const).map(pr => {
                      const isActive = taskDrawerPriority === pr;
                      return (
                        <Button
                          key={pr}
                          type={isActive ? 'primary' : 'default'}
                          size="small"
                          onClick={() => setTaskDrawerPriority(pr)}
                        >
                          {pr === 'low' ? t('chat.low') : pr === 'medium' ? t('chat.medium') : pr === 'high' ? t('chat.high') : t('chat.urgent')}
                        </Button>
                      );
                    })}
                  </Space>
                </div>

                <div className="p-3.5 rounded-lg text-xs leading-relaxed select-none" style={{
                  background: isDark ? '#111d2c' : '#f0f5ff',
                  borderColor: isDark ? '#15325b' : '#d6e4ff',
                  border: `1px solid ${isDark ? '#15325b' : '#d6e4ff'}`,
                  color: isDark ? '#a6a6a6' : '#595959'
                }}>
                  <b>{t('chat.bidirectional')}</b> {t('chat.bidirectionalDesc')}
                </div>
              </div>
            </div>

            <div className="flex gap-2 pt-4 border-t" style={{ borderColor: isDark ? '#303030' : '#f0f0f0' }}>
              <Button block onClick={() => setTaskDrawerMsg(null)}>{t('common.cancel')}</Button>
              <Button block type="primary" onClick={handleExecuteTaskDrawer}>{t('chat.saveAndPublish')}</Button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
};
