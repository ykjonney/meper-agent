import React, { createContext, useContext, useState, useEffect } from 'react';
import { Agent, Skill, MCPServer, Task, Chat, Message, SubTask, TimelineEntry, PresetNode, Flow, User, Role, Permission } from './types';
import { initialAgents, initialSkills, initialMCPServers, initialTasks, initialChats, initialPresetNodes, initialFlows, initialUsers, initialRoles, initialPermissions } from './mockData';

export type Tab = 'agents' | 'skills' | 'mcp' | 'tasks' | 'chat' | 'flows' | 'nodes' | 'users' | 'roles' | 'permissions' | 'profile';
export type AuthView = 'app' | 'login' | 'register';

interface AppContextType {
  agents: Agent[];
  skills: Skill[];
  mcpServers: MCPServer[];
  tasks: Task[];
  chats: Chat[];
  flows: Flow[];
  presetNodes: PresetNode[];
  activeTab: Tab;
  setActiveTab: (tab: Tab) => void;
  
  // Navigation variables
  selectedAgentId: string | null;
  setSelectedAgentId: (id: string | null) => void;
  currentChatId: string | null;
  setCurrentChatId: (id: string | null) => void;
  
  // Focus variables
  focusedAgentId: string | null;
  setFocusedAgentId: (id: string | null) => void;
  focusedSkillId: string | null;
  setFocusedSkillId: (id: string | null) => void;
  focusedMCPServerId: string | null;
  setFocusedMCPServerId: (id: string | null) => void;
  focusedTaskId: string | null;
  setFocusedTaskId: (id: string | null) => void;
  focusedFlowId: string | null;
  setFocusedFlowId: (id: string | null) => void;
  focusedPresetNodeId: string | null;
  setFocusedPresetNodeId: (id: string | null) => void;
  
  // Creation editors
  editingAgentId: string | null; // null for add, 'new' for creating, id for editing
  setEditingAgentId: (id: string | null) => void;
  editingSkillId: string | null;
  setEditingSkillId: (id: string | null) => void;
  editingMCPServerId: string | null;
  setEditingMCPServerId: (id: string | null) => void;
  editingTaskId: string | null;
  setEditingTaskId: (id: string | null) => void;
  editingFlowId: string | null;
  setEditingFlowId: (id: string | null) => void;
  editingPresetNodeId: string | null;
  setEditingPresetNodeId: (id: string | null) => void;

  // Actions
  addAgent: (agent: Omit<Agent, 'id'>) => Agent;
  updateAgent: (agent: Agent) => void;
  deleteAgent: (id: string) => void;
  
  addSkill: (skill: Omit<Skill, 'id'>) => Skill;
  updateSkill: (skill: Skill) => void;
  deleteSkill: (id: string) => void;
  
  addMCPServer: (server: Omit<MCPServer, 'id'>) => MCPServer;
  updateMCPServer: (server: MCPServer) => void;
  deleteMCPServer: (id: string) => void;
  toggleMCPConnection: (id: string) => void;
  triggerMCPDiscovery: (id: string) => void;

  addTask: (task: Omit<Task, 'id' | 'createdAt' | 'updatedAt' | 'progress' | 'timeline'>) => Task;
  updateTask: (task: Task) => void;
  deleteTask: (id: string) => void;
  advanceTaskStatus: (id: string, nextStatus: Task['status']) => void;
  
  addChat: (agentId: string) => Chat;
  deleteChat: (id: string) => void;
  sendChatMessage: (chatId: string, text: string) => void;
  convertMessageToTask: (chatId: string, messageId: string, title?: string, priority?: Task['priority']) => Task;
  triggerAgentTaskSuggestion: (chatId: string) => void;
  delegateChatExecutionToBackground: (chatId: string, messageId: string) => void;

  // Flow & Node Actions
  addPresetNode: (node: Omit<PresetNode, 'id'>) => PresetNode;
  updatePresetNode: (node: PresetNode) => void;
  deletePresetNode: (id: string) => void;
  addFlow: (flow: Omit<Flow, 'id' | 'createdAt'>) => Flow;
  updateFlow: (flow: Flow) => void;
  deleteFlow: (id: string) => void;
  triggerFlow: (flowId: string) => Task;
  
  // Notification system
  notifications: Array<{ id: string; type: 'success' | 'warning' | 'error'; message: string }>;
  showNotification: (type: 'success' | 'warning' | 'error', message: string) => void;
  dismissNotification: (id: string) => void;

  // Auth
  currentUser: User | null;
  authView: AuthView;
  setAuthView: (view: AuthView) => void;
  login: (username: string, password: string) => boolean;
  logout: () => void;
  register: (data: { username: string; email: string; password: string; roleIds: string[] }) => boolean;
  updateProfile: (updates: Partial<Pick<User, 'email' | 'phone' | 'department' | 'bio'>>) => void;
  changePassword: (oldPassword: string, newPassword: string) => boolean;

  // User management
  users: User[];
  addUser: (user: Omit<User, 'id' | 'createdAt'>) => User;
  updateUser: (user: User) => void;
  deleteUser: (id: string) => void;

  // Role management
  roles: Role[];
  addRole: (role: Omit<Role, 'id' | 'createdAt'>) => Role;
  updateRole: (role: Role) => void;
  deleteRole: (id: string) => void;

  // Permission management
  permissions: Permission[];
  updatePermission: (id: string, updates: Partial<Permission>) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppStateProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Try loading from localStorage
  const [agents, setAgents] = useState<Agent[]>(() => {
    const saved = localStorage.getItem('agentplat_agents');
    return saved ? JSON.parse(saved) : initialAgents;
  });

  const [skills, setSkills] = useState<Skill[]>(() => {
    const saved = localStorage.getItem('agentplat_skills');
    return saved ? JSON.parse(saved) : initialSkills;
  });

  const [mcpServers, setMcpServers] = useState<MCPServer[]>(() => {
    const saved = localStorage.getItem('agentplat_mcp');
    return saved ? JSON.parse(saved) : initialMCPServers;
  });

  const [tasks, setTasks] = useState<Task[]>(() => {
    const saved = localStorage.getItem('agentplat_tasks');
    return saved ? JSON.parse(saved) : initialTasks;
  });

  const [chats, setChats] = useState<Chat[]>(() => {
    const saved = localStorage.getItem('agentplat_chats');
    return saved ? JSON.parse(saved) : initialChats;
  });

  const [flows, setFlows] = useState<Flow[]>(() => {
    const saved = localStorage.getItem('agentplat_flows');
    return saved ? JSON.parse(saved) : initialFlows;
  });

  const [presetNodes, setPresetNodes] = useState<PresetNode[]>(() => {
    const saved = localStorage.getItem('agentplat_presetnodes');
    return saved ? JSON.parse(saved) : initialPresetNodes;
  });

  const [activeTab, setActiveTabState] = useState<Tab>(() => {
    const saved = localStorage.getItem('agentplat_activetab');
    return (saved as Tab) || 'agents';
  });

  // UI Flow indicators
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [currentChatId, setCurrentChatId] = useState<string | null>(() => {
    const saved = localStorage.getItem('agentplat_currentchatid');
    return saved || (initialChats.length > 0 ? initialChats[0].id : null);
  });
  
  const [focusedAgentId, setFocusedAgentId] = useState<string | null>(null);
  const [focusedSkillId, setFocusedSkillId] = useState<string | null>(null);
  const [focusedMCPServerId, setFocusedMCPServerId] = useState<string | null>(null);
  const [focusedTaskId, setFocusedTaskId] = useState<string | null>(null);
  const [focusedFlowId, setFocusedFlowId] = useState<string | null>(null);
  const [focusedPresetNodeId, setFocusedPresetNodeId] = useState<string | null>(null);
  
  const [editingAgentId, setEditingAgentId] = useState<string | null>(null);
  const [editingSkillId, setEditingSkillId] = useState<string | null>(null);
  const [editingMCPServerId, setEditingMCPServerId] = useState<string | null>(null);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editingFlowId, setEditingFlowId] = useState<string | null>(null);
  const [editingPresetNodeId, setEditingPresetNodeId] = useState<string | null>(null);

  const [notifications, setNotifications] = useState<Array<{ id: string; type: 'success' | 'warning' | 'error'; message: string }>>([]);

  // Auth state
  const [users, setUsers] = useState<User[]>(() => {
    const saved = localStorage.getItem('agentplat_users');
    return saved ? JSON.parse(saved) : initialUsers;
  });

  const [roles, setRoles] = useState<Role[]>(() => {
    const saved = localStorage.getItem('agentplat_roles');
    return saved ? JSON.parse(saved) : initialRoles;
  });

  const [permissions, setPermissions] = useState<Permission[]>(() => {
    const saved = localStorage.getItem('agentplat_permissions');
    return saved ? JSON.parse(saved) : initialPermissions;
  });

  const [currentUser, setCurrentUser] = useState<User | null>(() => {
    const savedId = localStorage.getItem('agentplat_currentuser');
    if (savedId) {
      const savedUsers = localStorage.getItem('agentplat_users');
      const userList: User[] = savedUsers ? JSON.parse(savedUsers) : initialUsers;
      return userList.find(u => u.id === savedId) || null;
    }
    return null;
  });

  const [authView, setAuthView] = useState<AuthView>(() => {
    return currentUser ? 'app' : 'login';
  });

  // Persists databases on change
  useEffect(() => {
    localStorage.setItem('agentplat_agents', JSON.stringify(agents));
  }, [agents]);

  useEffect(() => {
    localStorage.setItem('agentplat_skills', JSON.stringify(skills));
  }, [skills]);

  useEffect(() => {
    localStorage.setItem('agentplat_mcp', JSON.stringify(mcpServers));
  }, [mcpServers]);

  useEffect(() => {
    localStorage.setItem('agentplat_tasks', JSON.stringify(tasks));
  }, [tasks]);

  useEffect(() => {
    localStorage.setItem('agentplat_chats', JSON.stringify(chats));
  }, [chats]);

  useEffect(() => {
    localStorage.setItem('agentplat_flows', JSON.stringify(flows));
  }, [flows]);

  useEffect(() => {
    localStorage.setItem('agentplat_presetnodes', JSON.stringify(presetNodes));
  }, [presetNodes]);

  useEffect(() => {
    localStorage.setItem('agentplat_users', JSON.stringify(users));
  }, [users]);

  useEffect(() => {
    localStorage.setItem('agentplat_roles', JSON.stringify(roles));
  }, [roles]);

  useEffect(() => {
    localStorage.setItem('agentplat_permissions', JSON.stringify(permissions));
  }, [permissions]);

  useEffect(() => {
    if (currentUser) {
      localStorage.setItem('agentplat_currentuser', currentUser.id);
    } else {
      localStorage.removeItem('agentplat_currentuser');
    }
  }, [currentUser]);

  const setActiveTab = (tab: Tab) => {
    setActiveTabState(tab);
    localStorage.setItem('agentplat_activetab', tab);
  };

  useEffect(() => {
    if (currentChatId) {
      localStorage.setItem('agentplat_currentchatid', currentChatId);
    } else {
      localStorage.removeItem('agentplat_currentchatid');
    }
  }, [currentChatId]);

  // Notifications
  const showNotification = (type: 'success' | 'warning' | 'error', message: string) => {
    const id = Date.now().toString() + Math.random().toString(36).substr(2, 5);
    setNotifications(prev => [...prev, { id, type, message }]);
    
    // Automatically close standard success alerts after 4s
    setTimeout(() => {
      dismissNotification(id);
    }, 4500);
  };

  const dismissNotification = (id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  };

  // Simulated live-loop ticker for running background Tasks
  useEffect(() => {
    const interval = setInterval(() => {
      setTasks(currentTasks => {
        let changed = false;
        const nextTasks = currentTasks.map(task => {
          if (task.status === 'running' && task.progress < 100) {
            changed = true;

            // 1. Core Flow sequential execution mode
            if (task.flowId) {
              const currentStep = task.currentStepIndex !== undefined ? task.currentStepIndex : 0;
              const nextSubtasks = [...task.subtasks];
              const activeSubtask = nextSubtasks[currentStep];

              if (activeSubtask) {
                const increment = Math.floor(Math.random() * 25) + 15; // Fast progression for beautiful preview (15-40%)
                const newSubProg = Math.min(100, activeSubtask.progress + increment);
                const isSubFinished = newSubProg === 100;

                nextSubtasks[currentStep] = {
                  ...activeSubtask,
                  progress: newSubProg,
                  status: isSubFinished ? 'completed' : 'running'
                };

                let nextStep = currentStep;
                const nextTimeline = [...task.timeline];

                if (isSubFinished) {
                  nextStep = currentStep + 1;
                  nextTimeline.push({
                    id: 't-flow-step-finished-' + Date.now(),
                    time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
                    status: '节点完成',
                    message: `流水线单元 [${activeSubtask.title}] 执行完毕。数据及参数安全向下派发。`
                  });

                  if (nextStep < nextSubtasks.length) {
                    nextSubtasks[nextStep] = {
                      ...nextSubtasks[nextStep],
                      status: 'running',
                      progress: 10
                    };
                    nextTimeline.push({
                      id: 't-flow-step-start-' + Date.now(),
                      time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
                      status: '节点激活',
                      message: `工作流自动流转！正在调度并拉起下个算子节点：[${nextSubtasks[nextStep].title}]。`
                    });
                  }
                }

                const isFlowFinished = nextStep >= nextSubtasks.length;
                const calculatedProg = Math.min(99, Math.floor((nextStep / nextSubtasks.length) * 100));
                const taskTotalProg = isFlowFinished ? 100 : calculatedProg;

                if (isFlowFinished) {
                  nextTimeline.push({
                    id: 't-flow-complete-' + Date.now(),
                    time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
                    status: '已跑通',
                    message: `🎉 恭喜！流水线关联的所有节点算子已顺序执行完毕。生成的商业周报 pdf 及图表已成功归档入库。`
                  });
                  showNotification('success', `工作流「${task.title}」已全部执行完毕！`);
                }

                return {
                  ...task,
                  progress: taskTotalProg,
                  status: isFlowFinished ? 'completed' : 'running',
                  currentStepIndex: nextStep,
                  subtasks: nextSubtasks,
                  timeline: nextTimeline,
                  updatedAt: new Date().toLocaleDateString('zh-CN') + ' ' + new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
                };
              }
            }

            // 2. Standard Task execution mode
            const newProgress = Math.min(100, task.progress + Math.floor(Math.random() * 8) + 3);
            const isFinished = newProgress === 100;
            
            // Advance running subtasks
            const nextSubtasks = task.subtasks.map(sub => {
              if (sub.status === 'running') {
                const subProg = Math.min(100, sub.progress + Math.floor(Math.random() * 20) + 10);
                return {
                  ...sub,
                  progress: subProg,
                  status: subProg === 100 ? 'completed' : 'running'
                };
              } else if (sub.status === 'pending' && Math.random() > 0.6) {
                // Pick first pending and run it
                return { ...sub, status: 'running', progress: 10 };
              }
              return sub;
            });

            // Ensure if progress is 100, we mark running subtasks completed
            const finalSubtasks = isFinished
              ? nextSubtasks.map(s => ({ ...s, status: 'completed' as const, progress: 100 }))
              : nextSubtasks;

            // Generate timeline notes
            const nextTimeline = [...task.timeline];
            if (isFinished) {
              nextTimeline.push({
                id: 't-finish-' + Date.now(),
                time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
                status: '已完成',
                message: '自动化流水线已成功跑通。产生的资产文件已归档。'
              });
              
              // Trigger a notification
              showNotification('success', `任务「${task.title}」已运行完毕！已生成输出报告。`);
              
              // If connected with a chat, append finished card message
              setTimeout(() => {
                if (task.sourceChatId) {
                  setChats(prevChats => prevChats.map(c => {
                    if (c.id === task.sourceChatId) {
                      const finalOutputStr = JSON.stringify({
                        status: 'success',
                        completedAt: new Date().toISOString(),
                        summary: `分析报告自动归档成功。${task.title} 总耗时为 ${Math.floor(Math.random() * 80) + 20} 秒。`,
                        artifacts: ["/workspace/final_sales_insights_0605.pdf"]
                      }, null, 2);
                      
                      const pushMsg: Message = {
                        id: 'msg-push-' + Date.now(),
                        sender: 'system',
                        text: `您订阅的追踪事务已在后台顺利执行完毕！`,
                        timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
                        taskCard: {
                          taskId: task.id,
                          title: task.title,
                          priority: task.priority,
                          status: 'completed',
                          progress: 100,
                          subtasks: finalSubtasks,
                          resultSummary: `分析指标已就绪！Q1业绩表现亮眼，环比扩张15%，已成功下载 Q1_sales_report.pdf。`
                        }
                      };
                      return {
                        ...c,
                        messages: [...c.messages, pushMsg]
                      };
                    }
                    return c;
                  }));
                }
              }, 500);
            } else if (Math.random() > 0.82) {
              nextTimeline.push({
                id: 't-step-' + Date.now(),
                time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
                status: '执行中',
                message: `调度器完成第 ${nextSubtasks.filter(s => s.status === 'completed').length} 个节点的安全验证，正在流式下发子模块。`
              });
            }

            return {
              ...task,
              progress: newProgress,
              status: isFinished ? 'completed' : 'running',
              subtasks: finalSubtasks,
              timeline: nextTimeline,
              updatedAt: new Date().toLocaleDateString('zh-CN') + ' ' + new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
            };
          }
          return task;
        });

        if (changed) {
          return nextTasks;
        }
        return currentTasks;
      });
    }, 5500);

    return () => clearInterval(interval);
  }, [presetNodes]);

  // CRUD Operators
  // 1. Agent
  const addAgent = (agent: Omit<Agent, 'id'>) => {
    const id = 'agent-' + Math.random().toString(36).substring(2, 9);
    const newAgent: Agent = {
      ...agent,
      id,
    };
    setAgents(prev => [...prev, newAgent]);
    showNotification('success', `Agent「${newAgent.name}」创建成功！`);
    return newAgent;
  };

  const updateAgent = (updated: Agent) => {
    setAgents(prev => prev.map(a => a.id === updated.id ? updated : a));
    showNotification('success', `Agent「${updated.name}」配置已成功保存。`);
  };

  const deleteAgent = (id: string) => {
    const agent = agents.find(a => a.id === id);
    setAgents(prev => prev.filter(a => a.id !== id));
    showNotification('warning', `Agent「${agent?.name || id}」已被删除。`);
  };

  // 2. Skill
  const addSkill = (skill: Omit<Skill, 'id'>) => {
    const id = 'skill-' + Math.random().toString(36).substring(2, 9);
    const newSkill: Skill = {
      ...skill,
      id,
    };
    setSkills(prev => [...prev, newSkill]);
    showNotification('success', `自定义 Skill「${newSkill.name}」已成功注册！`);
    return newSkill;
  };

  const updateSkill = (updated: Skill) => {
    setSkills(prev => prev.map(s => s.id === updated.id ? updated : s));
    showNotification('success', `Skill「${updated.name}」配置已更新。`);
  };

  const deleteSkill = (id: string) => {
    const skill = skills.find(s => s.id === id);
    setSkills(prev => prev.filter(s => s.id !== id));
    showNotification('warning', `Skill「${skill?.name || id}」已从平台注销。`);
  };

  // 3. MCP Server
  const addMCPServer = (server: Omit<MCPServer, 'id'>) => {
    const id = 'mcp-' + Math.random().toString(36).substring(2, 9);
    const newServer: MCPServer = {
      ...server,
      id,
    };
    setMcpServers(prev => [...prev, newServer]);
    showNotification('success', `MCP Server「${newServer.name}」已添加！`);
    return newServer;
  };

  const updateMCPServer = (updated: MCPServer) => {
    setMcpServers(prev => prev.map(s => s.id === updated.id ? updated : s));
    showNotification('success', `MCP Configuration「${updated.name}」已保存。`);
  };

  const deleteMCPServer = (id: string) => {
    const srv = mcpServers.find(s => s.id === id);
    setMcpServers(prev => prev.filter(s => s.id !== id));
    showNotification('warning', `MCP Server「${srv?.name || id}」已被移除。`);
  };

  const toggleMCPConnection = (id: string) => {
    setMcpServers(prev => prev.map(srv => {
      if (srv.id === id) {
        const toState = srv.status === 'connected' ? 'disconnected' : 'connecting';
        const logTime = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const newLogs = [...srv.logs];
        
        let finalStatus = toState;
        if (toState === 'connecting') {
          newLogs.push({
            time: logTime,
            fromStatus: srv.status,
            toStatus: 'connecting',
            message: `Initiating handshake connection stream to system driver...`
          });
          
          showNotification('success', `正在建立「${srv.name}」的通道进程...`);
          
          // Speed up secondary state
          setTimeout(() => {
            setMcpServers(current => current.map(c => {
              if (c.id === id) {
                const finishedLogTime = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                const finishedLogs = [...c.logs];
                finishedLogs.push({
                  time: finishedLogTime,
                  fromStatus: 'connecting',
                  toStatus: 'connected',
                  message: `Socket connection fully upgraded. 3 tools successfully synchronized.`
                });
                
                showNotification('success', `MCP「${c.name}」已顺利连接。`);
                return {
                  ...c,
                  status: 'connected',
                  logs: finishedLogs,
                  toolsCount: 3,
                  lastConnected: '刚刚'
                };
              }
              return c;
            }));
          }, 1500);
        } else {
          newLogs.push({
            time: logTime,
            fromStatus: srv.status,
            toStatus: 'disconnected',
            message: `Shutdown command issued. Connections terminated gracefully.`
          });
          showNotification('warning', `已优雅断开「${srv.name}」连接。`);
          finalStatus = 'disconnected';
        }

        return {
          ...srv,
          status: finalStatus,
          logs: newLogs,
          toolsCount: finalStatus === 'connected' ? srv.toolsCount : 0
        };
      }
      return srv;
    }));
  };

  const triggerMCPDiscovery = (id: string) => {
    setMcpServers(prev => prev.map(srv => {
      if (srv.id === id) {
        const logTime = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const newLogs = [...srv.logs];
        newLogs.push({
          time: logTime,
          fromStatus: srv.status,
          toStatus: srv.status,
          message: `Issued client schema discovery command: listTools(), listPrompts().`
        });
        showNotification('success', `正在发现「${srv.name}」暴露出的端点...`);
        return {
          ...srv,
          logs: newLogs
        };
      }
      return srv;
    }));
  };

  // 4. Tasks
  const addTask = (taskInput: Omit<Task, 'id' | 'createdAt' | 'updatedAt' | 'progress' | 'timeline'>) => {
    const id = 'task-' + Math.random().toString(36).substring(2, 9);
    const nowTime = new Date();
    const timeStr = nowTime.toLocaleDateString('zh-CN') + ' ' + nowTime.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    
    // Auto populate timeline
    const timeline: TimelineEntry[] = [
      {
        id: 't-init-' + Date.now(),
        time: nowTime.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        status: '已创建',
        message: '用户成功建立了任务，并将执行交给指定的 Agent 节点。'
      }
    ];

    const newTask: Task = {
      ...taskInput,
      id,
      progress: 0,
      createdAt: timeStr,
      updatedAt: timeStr,
      timeline
    };

    setTasks(prev => [newTask, ...prev]);
    showNotification('success', `Task「${newTask.title}」已注册！`);
    return newTask;
  };

  const updateTask = (updated: Task) => {
    setTasks(prev => prev.map(t => t.id === updated.id ? updated : t));
  };

  const deleteTask = (id: string) => {
    const current = tasks.find(t => t.id === id);
    setTasks(prev => prev.filter(t => t.id !== id));
    showNotification('warning', `已被清除。`);
  };

  const advanceTaskStatus = (id: string, nextStatus: Task['status']) => {
    const nowTime = new Date();
    const timeStr = nowTime.toLocaleDateString('zh-CN') + ' ' + nowTime.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const logTime = nowTime.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    setTasks(prev => prev.map(t => {
      if (t.id === id) {
        const nextTimeline = [...t.timeline];
        
        let statusText = '执行';
        if (nextStatus === 'planned') {
          statusText = '已规划';
          nextTimeline.push({
            id: 't-' + nextStatus + '-' + Date.now(),
            time: logTime,
            status: '已规划',
            message: 'Agent 读取了任务参数输入，建立了步骤分解序列树。'
          });
          
          // Generate mock subtasks if none exist
          const mockSubs: SubTask[] = [
            { id: 'sub-p1', title: '读取并且校验 SourceSchema', status: 'completed', progress: 100 },
            { id: 'sub-p2', title: '规划算法管道拓扑图', status: 'pending', progress: 0 },
            { id: 'sub-p3', title: '执行脚本数据生成指标快照', status: 'pending', progress: 0 }
          ];
          
          return {
            ...t,
            status: nextStatus,
            subtasks: t.subtasks.length === 0 ? mockSubs : t.subtasks,
            timeline: nextTimeline,
            updatedAt: timeStr
          };
        } else if (nextStatus === 'running') {
          statusText = '执行中';
          nextTimeline.push({
            id: 't-' + nextStatus + '-' + Date.now(),
            time: logTime,
            status: '执行中',
            message: '调度网关批准并拉起容器环境，准备执行子程序。'
          });
          
          // Set first non-completed subtask to running
          const updatedSubs = t.subtasks.map(sub => {
            if (sub.status !== 'completed' && sub.status !== 'running') {
              return { ...sub, status: 'running' as const, progress: 10 };
            }
            return sub;
          });

          return {
            ...t,
            status: nextStatus,
            subtasks: updatedSubs.length === 0 ? [
              { id: 'sub-r1', title: '执行调度运行任务节点', status: 'running', progress: 10 }
            ] : updatedSubs,
            timeline: nextTimeline,
            updatedAt: timeStr
          };
        } else if (nextStatus === 'paused') {
          statusText = '已暂停';
          nextTimeline.push({
            id: 't-' + nextStatus + '-' + Date.now(),
            time: logTime,
            status: '已暂停',
            message: '操作员执行了挂起命令，正在暂存当前缓存段。'
          });
        } else if (nextStatus === 'cancelled') {
          statusText = '已取消';
          nextTimeline.push({
            id: 't-' + nextStatus + '-' + Date.now(),
            time: logTime,
            status: '已取消',
            message: '操作员取消了事务，运行进程已终止并回收资源。'
          });
        } else if (nextStatus === 'completed') {
          statusText = '已完成';
          nextTimeline.push({
            id: 't-' + nextStatus + '-' + Date.now(),
            time: logTime,
            status: '已完成',
            message: '程序最终运行通过。输出数据报告及报表已成功就绪并封存。'
          });
          showNotification('success', `项目「${t.title}」已设定为完成状态。`);
        }

        return {
          ...t,
          status: nextStatus,
          timeline: nextTimeline,
          progress: nextStatus === 'completed' ? 100 : t.progress,
          subtasks: nextStatus === 'completed' ? t.subtasks.map(s => ({ ...s, status: 'completed' as const, progress: 100 })) : t.subtasks,
          updatedAt: timeStr
        };
      }
      return t;
    }));
  };

  // 5. Chats and real agent streaming conversations emulators
  const addChat = (agentId: string) => {
    const id = 'chat-' + Math.random().toString(36).substring(2, 9);
    const agentObj = agents.find(a => a.id === agentId);
    const welcome = agentObj?.persona.welcomeMessage || '你好！我是你的智能助手，随时为您效劳。';
    
    const newChat: Chat = {
      id,
      agentId,
      title: `${agentObj?.name || '机器人'} 对话`,
      updatedAt: '刚刚',
      messages: [
        {
          id: 'welcome-' + Date.now(),
          sender: 'agent',
          text: welcome,
          timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
        }
      ]
    };

    setChats(prev => [newChat, ...prev]);
    setCurrentChatId(id);
    setActiveTab('chat');
    showNotification('success', `和「${agentObj?.name}」的新对话已开辟。`);
    return newChat;
  };

  const deleteChat = (id: string) => {
    setChats(prev => prev.filter(c => c.id !== id));
    if (currentChatId === id) {
      setCurrentChatId(null);
    }
    showNotification('warning', `对话已成功移除。`);
  };

  // High quality dialog engine emulation
  const sendChatMessage = (chatId: string, userText: string) => {
    const timeStr = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const userMsgId = 'user-msg-' + Date.now();
    
    // Find chat and active agent
    const chat = chats.find(c => c.id === chatId);
    if (!chat) return;
    const activeAgent = agents.find(a => a.id === chat.agentId);

    // Append user message
    const userMsg: Message = {
      id: userMsgId,
      sender: 'user',
      text: userText,
      timestamp: timeStr
    };

    setChats(prev => prev.map(c => {
      if (c.id === chatId) {
        return {
          ...c,
          messages: [...c.messages, userMsg],
          updatedAt: '刚刚'
        };
      }
      return c;
    }));

    // Trigger progressive agent streaming, tool-use call sequence emulator:
    setTimeout(() => {
      // Create empty Agent state placeholder message with blinking cursor ▍
      const agentMsgId = 'agent-msg-' + Date.now();
      const waitingAgentMsg: Message = {
        id: agentMsgId,
        sender: 'agent',
        text: '让我来为您处理这个问题。▍',
        timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      };

      setChats(prev => prev.map(c => {
        if (c.id === chatId) {
          return {
            ...c,
            messages: [...c.messages, waitingAgentMsg]
          };
        }
        return c;
      }));

      // STEP 1: TRIGGER TOOL USE EMULATION (if query demands tools, or randomly)
      let usesTool = false;
      let toolName = 'web_search';
      let toolArgs = '{"query": "..."}';
      let toolOut = '[]';

      if (userText.includes('分析') || userText.includes('报告') || userText.includes('数据') || userText.includes('Q1')) {
        usesTool = true;
        toolName = 'data_analysis';
        toolArgs = JSON.stringify({ filepath: "/workspace/sales_2026_q1.csv", analysis_type: "trend" }, null, 2);
        toolOut = JSON.stringify({ status: "success", rows_processed: 1250, velocity: "1.2 MB/s", summary: "Q1 sales growth spikes at 15%." }, null, 2);
      } else if (userText.includes('代码') || userText.includes('写') || userText.includes('脚本')) {
        usesTool = true;
        toolName = 'code_execute';
        toolArgs = JSON.stringify({ code: "def analyze():\n    return 'Q1 stable metrics'" }, null, 2);
        toolOut = JSON.stringify({ stdout: "Execution success\n", exit_code: 0 }, null, 2);
      } else {
        usesTool = true; // default search fallback to make it beautiful
        toolName = 'web_search';
        toolArgs = JSON.stringify({ query: userText, max_results: 3 }, null, 2);
        toolOut = JSON.stringify([
          { title: "2026 AI Insight News", url: "https://news.ai/2026", snippet: "Agents coordinates through standard environment connectors..." }
        ], null, 2);
      }

      setTimeout(() => {
        // Update agent message placing the tool placeholder card inside running state
        setChats(prev => prev.map(c => {
          if (c.id === chatId) {
            return {
              ...c,
              messages: c.messages.map(m => {
                if (m.id === agentMsgId) {
                  return {
                    ...m,
                    text: '我需要调派底层工具来辅助提取数据和定位问题。▍',
                    toolCalls: [
                      {
                        id: 'tc-' + Date.now(),
                        name: toolName,
                        args: toolArgs,
                        status: 'running'
                      }
                    ]
                  };
                }
                return m;
              })
            };
          }
          return c;
        }));

        // STEP 2: FINISH TOOL WITH SUCCESS
        setTimeout(() => {
          setChats(prev => prev.map(c => {
            if (c.id === chatId) {
              return {
                ...c,
                messages: c.messages.map(m => {
                  if (m.id === agentMsgId && m.toolCalls) {
                    return {
                      ...m,
                      text: '工具执行完毕，正在结构化汇总并撰写最后的分析解答。▍',
                      toolCalls: m.toolCalls.map(tc => ({
                        ...tc,
                        status: 'success',
                        result: toolOut,
                        duration: 1.8
                      }))
                    };
                  }
                  return m;
                })
              };
            }
            return c;
          }));

          // STEP 3: OUTPUT LATEST WORDS + AUTOMATIC PERSIST TARGET CARD OR RECOMMENDATION
          setTimeout(() => {
            setChats(prev => prev.map(c => {
              if (c.id === chatId) {
                return {
                  ...c,
                  messages: c.messages.map(m => {
                    if (m.id === agentMsgId) {
                      let finalResponse = `针对您的需求：**"${userText}"**，我已经完成了对应沙盒文件的查询与提取。\n\n根据工具返回，指标数据平稳，特定高危偏离已被过滤。2026 业务规划可继续稳步前进。\n\n目前检测到此流程比较繁杂，且涉及后续的多阶段深度执行，**我提议最好将这个事务创建为在后台静默运行并可以持续追踪的 Task 作业节点**，以便随时监督任务多模块的打标和运行结果。`;
                      
                      // Also provide suggestion card
                      const isComplex = userText.includes('分析') || userText.includes('全面') || userText.includes('任务') || userText.includes('做') || userText.includes('整理');
                      
                      return {
                        ...m,
                        text: finalResponse,
                        suggestionCard: isComplex ? {
                          title: userText.length > 25 ? userText.substring(0, 22) + '...' : userText,
                          stepsCount: 5,
                          eta: '~ 10 分钟'
                        } : undefined
                      };
                    }
                    return m;
                  })
                };
              }
              return c;
            }));
          }, 2000);

        }, 2200);

      }, 1500);

    }, 1000);
  };

  const convertMessageToTask = (chatId: string, messageId: string, title?: string, priority?: Task['priority']) => {
    const chat = chats.find(c => c.id === chatId);
    if (!chat) throw new Error('Chat not found');
    const msg = chat.messages.find(m => m.id === messageId);
    if (!msg) throw new Error('Message not found');

    const agentObj = agents.find(a => a.id === chat.agentId);

    // Create the task
    const createdTask = addTask({
      title: title || `从对话提取: ${msg.text.substring(0, 18)}...`,
      description: msg.text,
      status: 'running', // Start immediately!
      priority: priority || 'high',
      agentId: chat.agentId,
      subtasks: [
        { id: 'sub-c1', title: '读取对话历史语境', status: 'completed', progress: 100 },
        { id: 'sub-c2', title: '执行对话委委派指令', status: 'running', progress: 15 },
        { id: 'sub-c3', title: '归档输出结果至 PDF 报告', status: 'pending', progress: 0 }
      ],
      tags: agentObj ? agentObj.tags : ['对关联'],
      input: JSON.stringify({ textSource: msg.text, originChat: chatId }, null, 2),
      maxRetries: 3,
      timeout: 3600,
      sourceChatId: chatId
    });

    // Replace the message or append a system notification card inside chat
    setChats(prev => prev.map(c => {
      if (c.id === chatId) {
        // Clear suggestion cards on trigger and inject Task system card
        const updatedMessages = c.messages.map(m => {
          if (m.id === messageId) {
            return {
              ...m,
              suggestionCard: undefined // close suggestions
            };
          }
          return m;
        });

        const timeStr = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        const systemTaskCardMsg: Message = {
          id: 'sys-task-card-' + Date.now(),
          sender: 'system',
          text: `👌 成功从本段对话内容将请求打包为 Task 工单并在后台执行中。状态和进度正在与任务看板和 Agent 进程保持实时同步轮询。`,
          timestamp: timeStr,
          taskCard: {
            taskId: createdTask.id,
            title: createdTask.title,
            priority: createdTask.priority,
            status: 'running',
            progress: 15,
            subtasks: createdTask.subtasks
          }
        };

        return {
          ...c,
          messages: [...updatedMessages, systemTaskCardMsg]
        };
      }
      return c;
    }));

    showNotification('success', `Task「${createdTask.title}」已在后台开始运作！`);
    return createdTask;
  };

  const triggerAgentTaskSuggestion = (chatId: string) => {
    // Manually push a mock suggestion card
    const timeStr = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    setChats(prev => prev.map(c => {
      if (c.id === chatId) {
        const suggestionMsg: Message = {
          id: 'sys-suggest-' + Date.now(),
          sender: 'agent',
          text: '当前的工作流需要经历多波段工具清洗、代码沙漏编译、以及复杂的报表绘制。我极度建议拉起一个独立的后台 Task 进行精细管理：',
          timestamp: timeStr,
          suggestionCard: {
            title: "多源混合数据清洗及高阶聚类分析系统",
            stepsCount: 5,
            eta: '~15 分钟'
          }
        };
        return {
          ...c,
          messages: [...c.messages, suggestionMsg]
        };
      }
      return c;
    }));
  };

  const delegateChatExecutionToBackground = (chatId: string, messageId: string) => {
    const chat = chats.find(c => c.id === chatId);
    if (!chat) return;
    const msg = chat.messages.find(m => m.id === messageId);
    if (!msg) return;

    // Simulate task creation
    const t = convertMessageToTask(chatId, messageId, `委派处理: ${msg.text.substring(0, 15)}`);
    
    // Add warning banner update
    setChats(prev => prev.map(c => {
      if (c.id === chatId) {
        return {
          ...c,
          messages: c.messages.map(m => {
            if (m.id === messageId) {
              return {
                ...m,
                delegationTip: {
                  taskId: t.id,
                  progress: 15
                }
              };
            }
            return m;
          })
        };
      }
      return c;
    }));
  };

  // 5. PresetNodes CRUD
  const addPresetNode = (node: Omit<PresetNode, 'id'>) => {
    const id = 'node-' + Math.random().toString(36).substring(2, 9);
    const newNode: PresetNode = { ...node, id };
    setPresetNodes(prev => [...prev, newNode]);
    showNotification('success', `预设节点「${newNode.name}」注册成功！`);
    return newNode;
  };

  const updatePresetNode = (updated: PresetNode) => {
    setPresetNodes(prev => prev.map(n => n.id === updated.id ? updated : n));
    showNotification('success', `预设节点「${updated.name}」已保存。`);
  };

  const deletePresetNode = (id: string) => {
    const node = presetNodes.find(n => n.id === id);
    setPresetNodes(prev => prev.filter(n => n.id !== id));
    showNotification('warning', `预设节点「${node?.name || id}」已被移除。`);
  };

  // 6. Flows CRUD
  const addFlow = (flow: Omit<Flow, 'id' | 'createdAt'>) => {
    const id = 'flow-' + Math.random().toString(36).substring(2, 9);
    const newFlow: Flow = {
      ...flow,
      id,
      createdAt: new Date().toLocaleDateString('zh-CN')
    };
    setFlows(prev => [...prev, newFlow]);
    showNotification('success', `工作流「${newFlow.name}」创建成功！`);
    return newFlow;
  };

  const updateFlow = (updated: Flow) => {
    setFlows(prev => prev.map(f => f.id === updated.id ? updated : f));
    showNotification('success', `工作流「${updated.name}」配置已成功保存。`);
  };

  const deleteFlow = (id: string) => {
    const flow = flows.find(f => f.id === id);
    setFlows(prev => prev.filter(f => f.id !== id));
    showNotification('warning', `工作流「${flow?.name || id}」已被删除。`);
  };

  const triggerFlow = (flowId: string) => {
    const flow = flows.find(f => f.id === flowId);
    if (!flow) throw new Error('Flow not found');

    const mappedSubtasks: SubTask[] = flow.nodes.map((nodeRef, index) => {
      const preset = presetNodes.find(pn => pn.id === nodeRef.nodeId);
      const agentObj = agents.find(a => a?.id === preset?.agentId);
      return {
        id: 'flow-step-' + index + '-' + Date.now(),
        title: `${preset?.name || '未知步骤'} (${agentObj?.name || '未知智能体'})`,
        status: index === 0 ? 'running' : 'pending',
        progress: index === 0 ? 10 : 0
      };
    });

    const taskId = 'task-flow-run-' + Math.random().toString(36).substring(2, 9);
    const nowTime = new Date();
    const timeStr = nowTime.toLocaleDateString('zh-CN') + ' ' + nowTime.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

    const timeline: TimelineEntry[] = [
      {
        id: 't-init-' + Date.now(),
        time: nowTime.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        status: '开始执行',
        message: `工作流「${flow.name}」被手动触发。正在调度运行，当前序列共 ${mappedSubtasks.length} 个节点算子。`
      }
    ];

    const firstPreset = presetNodes.find(pn => pn.id === flow.nodes[0]?.nodeId);
    const fallbackAgentId = firstPreset?.agentId || agents[0]?.id || '';

    const newTask: Task = {
      id: taskId,
      title: `流水线: ${flow.name}`,
      description: flow.description,
      status: 'running',
      priority: 'high',
      agentId: fallbackAgentId,
      progress: 5,
      tags: ['流水线', '自动化'],
      input: JSON.stringify({ flowId: flow.id, nodesCount: flow.nodes.length, triggeredAt: nowTime.toISOString() }, null, 2),
      maxRetries: 3,
      timeout: 3600,
      createdAt: timeStr,
      updatedAt: timeStr,
      subtasks: mappedSubtasks,
      timeline,
      flowId: flow.id,
      currentStepIndex: 0
    };

    setTasks(prev => [newTask, ...prev]);

    // Update last triggered at on flow
    setFlows(prev => prev.map(f => f.id === flowId ? { ...f, lastTriggeredAt: nowTime.toLocaleDateString('zh-CN') + ' ' + nowTime.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) } : f));

    showNotification('success', `工作流「${flow.name}」已开始流转，可在任务看板中追踪节点。`);
    return newTask;
  };

  // ── Auth ──
  const login = (username: string, password: string): boolean => {
    const user = users.find(u => u.username === username && u.password === password && u.status === 'active');
    if (user) {
      const updated = { ...user, lastLoginAt: new Date().toLocaleDateString('zh-CN') + ' ' + new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) };
      setUsers(prev => prev.map(u => u.id === updated.id ? updated : u));
      setCurrentUser(updated);
      setAuthView('app');
      return true;
    }
    return false;
  };

  const logout = () => {
    setCurrentUser(null);
    setAuthView('login');
    localStorage.removeItem('agentplat_currentuser');
  };

  const register = (data: { username: string; email: string; password: string; roleIds: string[] }): boolean => {
    if (users.some(u => u.username === data.username)) return false;
    if (users.some(u => u.email === data.email)) return false;
    const id = 'user-' + Math.random().toString(36).substring(2, 9);
    const newUser: User = {
      id,
      username: data.username,
      email: data.email,
      password: data.password,
      status: 'active',
      roleIds: data.roleIds,
      createdAt: new Date().toLocaleDateString('zh-CN'),
    };
    setUsers(prev => [...prev, newUser]);
    setCurrentUser(newUser);
    setAuthView('app');
    return true;
  };

  const updateProfile = (updates: Partial<Pick<User, 'email' | 'phone' | 'department' | 'bio'>>) => {
    if (!currentUser) return;
    const updated = { ...currentUser, ...updates };
    setCurrentUser(updated);
    setUsers(prev => prev.map(u => u.id === updated.id ? updated : u));
    showNotification('success', '个人信息已保存。');
  };

  const changePassword = (oldPassword: string, newPassword: string): boolean => {
    if (!currentUser || currentUser.password !== oldPassword) return false;
    const updated = { ...currentUser, password: newPassword };
    setCurrentUser(updated);
    setUsers(prev => prev.map(u => u.id === updated.id ? updated : u));
    showNotification('success', '密码已修改。');
    return true;
  };

  // ── User CRUD ──
  const addUser = (input: Omit<User, 'id' | 'createdAt'>): User => {
    const id = 'user-' + Math.random().toString(36).substring(2, 9);
    const newUser: User = { ...input, id, createdAt: new Date().toLocaleDateString('zh-CN') };
    setUsers(prev => [...prev, newUser]);
    showNotification('success', `用户「${newUser.username}」创建成功！`);
    return newUser;
  };

  const updateUser = (updated: User) => {
    setUsers(prev => prev.map(u => u.id === updated.id ? updated : u));
    if (currentUser && currentUser.id === updated.id) {
      setCurrentUser(updated);
    }
    showNotification('success', `用户「${updated.username}」信息已保存。`);
  };

  const deleteUser = (id: string) => {
    const user = users.find(u => u.id === id);
    setUsers(prev => prev.filter(u => u.id !== id));
    showNotification('warning', `用户「${user?.username || id}」已被删除。`);
  };

  // ── Role CRUD ──
  const addRole = (input: Omit<Role, 'id' | 'createdAt'>): Role => {
    const id = 'role-' + Math.random().toString(36).substring(2, 9);
    const newRole: Role = { ...input, id, createdAt: new Date().toLocaleDateString('zh-CN') };
    setRoles(prev => [...prev, newRole]);
    showNotification('success', `角色「${newRole.name}」创建成功！`);
    return newRole;
  };

  const updateRole = (updated: Role) => {
    setRoles(prev => prev.map(r => r.id === updated.id ? updated : r));
    showNotification('success', `角色「${updated.name}」已保存。`);
  };

  const deleteRole = (id: string) => {
    const role = roles.find(r => r.id === id);
    setRoles(prev => prev.filter(r => r.id !== id));
    showNotification('warning', `角色「${role?.name || id}」已被删除。`);
  };

  // ── Permission ──
  const updatePermission = (id: string, updates: Partial<Permission>) => {
    setPermissions(prev => prev.map(p => p.id === id ? { ...p, ...updates } : p));
  };

  return (
    <AppContext.Provider value={{
      agents,
      skills,
      mcpServers,
      tasks,
      chats,
      flows,
      presetNodes,
      activeTab,
      setActiveTab,
      
      selectedAgentId,
      setSelectedAgentId,
      currentChatId,
      setCurrentChatId,
      
      focusedAgentId,
      setFocusedAgentId,
      focusedSkillId,
      setFocusedSkillId,
      focusedMCPServerId,
      setFocusedMCPServerId,
      focusedTaskId,
      setFocusedTaskId,
      focusedFlowId,
      setFocusedFlowId,
      focusedPresetNodeId,
      setFocusedPresetNodeId,
      
      editingAgentId,
      setEditingAgentId,
      editingSkillId,
      setEditingSkillId,
      editingMCPServerId,
      setEditingMCPServerId,
      editingTaskId,
      setEditingTaskId,
      editingFlowId,
      setEditingFlowId,
      editingPresetNodeId,
      setEditingPresetNodeId,

      addAgent,
      updateAgent,
      deleteAgent,
      
      addSkill,
      updateSkill,
      deleteSkill,
      
      addMCPServer,
      updateMCPServer,
      deleteMCPServer,
      toggleMCPConnection,
      triggerMCPDiscovery,

      addTask,
      updateTask,
      deleteTask,
      advanceTaskStatus,
      
      addChat,
      deleteChat,
      sendChatMessage,
      convertMessageToTask,
      triggerAgentTaskSuggestion,
      delegateChatExecutionToBackground,

      addPresetNode,
      updatePresetNode,
      deletePresetNode,
      addFlow,
      updateFlow,
      deleteFlow,
      triggerFlow,
      
      notifications,
      showNotification,
      dismissNotification,

      currentUser,
      authView,
      setAuthView,
      login,
      logout,
      register,
      updateProfile,
      changePassword,

      users,
      addUser,
      updateUser,
      deleteUser,

      roles,
      addRole,
      updateRole,
      deleteRole,

      permissions,
      updatePermission,
    }}>
      {children}
    </AppContext.Provider>
  );
};

export const useAppState = () => {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error('useAppState must be used within an AppStateProvider');
  }
  return context;
};
