import { Agent, Skill, MCPServer, Task, Chat, PresetNode, Flow, User, Role, Permission } from './types';

export const initialSkills: Skill[] = [
  {
    id: 'web_search',
    name: 'web_search',
    description: '网络搜索',
    type: 'Function',
    category: 'Built-in',
    version: '1.0.0',
    tags: ['搜索', '信息获取'],
    schema: JSON.stringify({
      query: {
        type: "string",
        description: "搜索关键词",
        required: true
      },
      max_results: {
        type: "integer",
        default: 5,
        maximum: 20
      }
    }, null, 2),
    testParams: JSON.stringify({
      query: "2026 AI 行业发展趋势",
      max_results: 5
    }, null, 2),
    mockOutput: JSON.stringify([
      {
        title: "2026年AI行业十大趋势 - 新华网",
        url: "https://news.cn/2026/01/trend",
        snippet: "随着大模型技术的快速推进，多模态交互和具身智能全面落地，Agent架构成为赋能各行业的核心系统。"
      },
      {
        title: "AI Agent 市场爆发式研究报告 - IDC",
        url: "https://idc.com/reports/2026/agent",
        snippet: "2026年企业级Agent架构应用渗透率大幅提升，成为办公流程优化、自动化决策的智算基座。"
      }
    ], null, 2)
  },
  {
    id: 'code_execute',
    name: 'code_execute',
    description: '代码执行',
    type: 'Function',
    category: 'Built-in',
    version: '1.0.0',
    tags: ['代码', '执行'],
    schema: JSON.stringify({
      code: {
        type: "string",
        description: "需要执行的脚本代码",
        required: true
      }
    }, null, 2),
    testParams: JSON.stringify({
      code: "print('Hello, AgentPlat 2026! Happy coding!')"
    }, null, 2),
    mockOutput: JSON.stringify({
      stdout: "Hello, AgentPlat 2026! Happy coding!\n",
      exit_code: 0,
      duration_ms: 45
    }, null, 2)
  },
  {
    id: 'data_analysis',
    name: 'data_analysis',
    description: '数据分析',
    type: 'Function',
    category: 'Custom',
    version: '1.2.0',
    tags: ['数据', '分析', '报告'],
    schema: JSON.stringify({
      filepath: {
        type: "string",
        description: "要分析的数据文件路径",
        required: true
      },
      analysis_type: {
        type: "string",
        enum: ["trend", "anomaly", "summary"],
        default: "trend"
      }
    }, null, 2),
    testParams: JSON.stringify({
      filepath: "/workspace/sales_2026_q1.csv",
      analysis_type: "trend"
    }, null, 2),
    mockOutput: JSON.stringify({
      status: "success",
      rows_processed: 5420,
      insights: [
        "Q1 总销售额 ¥2.3M，同比增长 15%",
        "检测到 3 个由于促销延迟导致的偏离异常值",
        "主要增幅集中在华东以及华南地区的数字消费类别"
      ],
      suggested_plot: "line_chart_sales_growth"
    }, null, 2)
  }
];

export const initialMCPServers: MCPServer[] = [
  {
    id: 'filesystem-mcp',
    name: 'filesystem-mcp',
    description: '文件系统操作 MCP Server',
    status: 'connected',
    connectionType: 'STDIO',
    lastConnected: '5 分钟前',
    toolsCount: 3,
    resourcesCount: 0,
    promptsCount: 0,
    tools: [
      {
        name: 'read_file',
        description: 'Read file contents from workspace sandbox',
        schema: JSON.stringify({
          path: { type: "string", description: "Absolute path inside workspace sandbox" }
        }, null, 2)
      },
      {
        name: 'write_file',
        description: 'Write or overwrite file contents in workspace sandbox',
        schema: JSON.stringify({
          path: { type: "string", description: "Target path inside workspace sandbox" },
          content: { type: "string", description: "Plain text content to save" }
        }, null, 2)
      },
      {
        name: 'list_directory',
        description: 'List directories under specified folder',
        schema: JSON.stringify({
          path: { type: "string", description: "Sandbox directory to traverse" }
        }, null, 2)
      }
    ],
    config: {
      command: 'npx',
      args: ['-y', '@modelcontextprotocol/server-filesystem', '/workspace'],
      env: [
        { key: 'ALLOWED_ROOT', value: '/workspace' }
      ],
      timeout: 30,
      reconnect: true,
      maxRetries: 3
    },
    logs: [
      { time: '10:30:00', fromStatus: 'disconnected', toStatus: 'connecting', message: 'Initiating stdio connection via process spawn: npx -y @modelcontextprotocol/server-filesystem /workspace' },
      { time: '10:30:01', fromStatus: 'connecting', toStatus: 'connected', message: 'Successfully connected. Handshake complete. 3 tools discovered.' }
    ]
  },
  {
    id: 'database-mcp',
    name: 'database-mcp',
    description: '数据库查询 MCP Server',
    status: 'disconnected',
    connectionType: 'SSE',
    lastConnected: '从不',
    error: 'Connection refused',
    toolsCount: 0,
    resourcesCount: 0,
    promptsCount: 0,
    tools: [],
    config: {
      url: 'http://localhost:8080/mcp',
      headers: [
        { key: 'Authorization', value: 'Bearer db-secret-token' }
      ],
      timeout: 15,
      reconnect: false
    },
    logs: [
      { time: '09:12:00', fromStatus: 'disconnected', toStatus: 'connecting', message: 'Attempting SSE connection stream to http://localhost:8080/mcp' },
      { time: '09:12:02', fromStatus: 'connecting', toStatus: 'disconnected', message: 'Error spawning connection: Connection refused. Check if database host is running and reachable.' }
    ]
  }
];

export const initialAgents: Agent[] = [
  {
    id: 'data-assistant',
    name: '数据分析助手',
    description: '帮助用户自动清洗原始销售数据，挖掘指标趋势并生成精美的可视化分析报告。',
    status: 'published',
    type: 'hybrid',
    tags: ['数据分析', '可视化', '报告'],
    systemPrompt: `你是一个专业的数据分析专家。你的职责是帮助用户：\n1. 分析数据趋势，得出统计模型；\n2. 识别业务波动和异常点，并做多维度溯源；\n3. 生成适合大屏幕或办公软件的高清分析图表。`,
    persona: {
      role: '数据分析专家',
      tone: '专业、清晰、有条理且注重商业洞察',
      welcomeMessage: '你好！我是你的数据分析助手。我已经连接了文件系统并且加载了数据算子，你可以上传或者指定 sandbox 数据文件，我来自动为你撰写分析报告并做指标看板预测。',
      constraints: [
        '只回答数据分析、商业指标和脚本执行相关的问题。',
        '回复必须逻辑严密，建议对核心数据使用加黑或图表标记。',
        '统一使用中文交流。'
      ]
    },
    models: [
      { model: 'claude-3-5-sonnet', priority: 10, maxTokens: 8192, temperature: 0.5, enabled: true },
      { model: 'claude-3-opus', priority: 5, maxTokens: 4096, temperature: 0.7, enabled: true }
    ],
    skills: ['web_search', 'code_execute', 'data_analysis'],
    mcpServers: ['filesystem-mcp'],
    flows: ['flow-sales-report'],
    visibility: 'org',
    version: '1.0.0'
  },
  {
    id: 'search-assistant',
    name: '知识搜索助手',
    description: '结合深度搜索技能，自动抓取国内外主流互联网科技白皮书与新闻源并结构化整理。',
    status: 'draft',
    type: 'conversational',
    tags: ['互联网搜索', '知识检索'],
    systemPrompt: `你是一名资深的互联网情报分析员。你的目标是接收用户的意图输入，规划搜索步骤，并通过外部搜索工具返回高质量信源整合结构。`,
    persona: {
      role: '高级情报挖掘专家',
      tone: '客观、求真、追求时效、详实规范',
      welcomeMessage: '你好，我是知识搜索助手。请输入你想调查或检索的信息主题，我会规划搜索步骤并给出包含准确出处链接的调查总结。',
      constraints: [
        '所有内容必须有外部事实做基础，避免臆测。',
        '对搜素结果进行智能去重与归类。'
      ]
    },
    models: [
      { model: 'claude-3-5-sonnet', priority: 1, maxTokens: 4000, temperature: 0.3, enabled: true }
    ],
    skills: ['web_search'],
    mcpServers: [],
    flows: [],
    visibility: 'me',
    version: '0.1.0'
  },
  {
    id: 'code-assistant',
    name: '代码极客助手',
    description: '协助开发者编写高质量 TypeScript 与 Python 代码，支持在安全沙箱环境中测试运行与多轮重试。',
    status: 'published',
    type: 'service',
    tags: ['代码编写', '仿真运行', '重构'],
    systemPrompt: `You are an elite software engineering assistant. Your priority is generating precise, bug-free, and well-typed code. Use the execution sandbox tool to verify code logic before delivering it.`,
    persona: {
      role: '全栈架构师',
      tone: '极简、技术精确、富有实战建议性',
      welcomeMessage: 'Hello developer! I am your Code Geek assistant. Toss me any algorithmic queries, refactoring tasks, or bug logs. I can execute python code in real time in the sandbox to test logic for you.',
      constraints: [
        'Always provide TypeScript types when writing JavaScript/React scripts.',
        'Adhere strictly to industry-standard modularity and clean code design patterns.'
      ]
    },
    models: [
      { model: 'claude-3-5-sonnet', priority: 10, maxTokens: 8192, temperature: 0.2, enabled: true }
    ],
    skills: ['code_execute'],
    mcpServers: ['filesystem-mcp'],
    flows: [],
    visibility: 'public',
    version: '1.1.2'
  }
];

export const initialTasks: Task[] = [
  {
    id: 'task-1',
    title: '分析 Q1 销售数据',
    description: '帮我全面分析一下 Q1 的销售数据，包括趋势、异常点、地区分布，最后生成报告。',
    status: 'running',
    priority: 'high',
    agentId: 'data-assistant',
    progress: 45,
    tags: ['数据分析', '报告'],
    input: JSON.stringify({
      data_source: "s3://company-sales/2026/q1_raw_sales.csv",
      analysis_type: "trend",
      output_format: "pdf"
    }, null, 2),
    output: undefined,
    maxRetries: 3,
    timeout: 3600,
    createdAt: '2026-06-05 10:00',
    updatedAt: '2026-06-05 10:15',
    subtasks: [
      { id: 'sub-1', title: '下载Q1原始销售数据', status: 'completed', progress: 100 },
      { id: 'sub-2', title: '数据清洗与类型预处理', status: 'completed', progress: 100 },
      { id: 'sub-3', title: '多维度指标趋势分析计算', status: 'running', progress: 30 },
      { id: 'sub-4', title: '生成高分辨率 SVG 可视化图表', status: 'pending', progress: 0 },
      { id: 'sub-5', title: '输出完整的 PDF 商业报告', status: 'pending', progress: 0 }
    ],
    timeline: [
      { id: 't-1', time: '10:00:12', status: '已创建', message: '由于与数据分析助手的对话消息，由用户手动转换为 Task 任务节点' },
      { id: 't-2', time: '10:01:05', status: '已规划', message: '数据分析助手通过思考树，自动生成了 5 步子任务拆解方案' },
      { id: 't-3', time: '10:02:00', status: '执行中', message: '操作员点击了「发布执行」，核心后台调度进程拉起，正在运行中...' }
    ],
    sourceChatId: 'chat-1'
  },
  {
    id: 'task-2',
    title: '客户负面反馈分类整理',
    description: '整理 2026 第一季度所有在社交媒体及产品工单中的偏负面反馈并提取重点改善意见。',
    status: 'created',
    priority: 'medium',
    agentId: 'data-assistant',
    progress: 0,
    tags: ['文本处理', '去重'],
    input: JSON.stringify({
      source_file: "/workspace/feedbacks_raw.xlsx",
      classification_categories: ["UI体验", "稳定度", "收费体系", "客服质量"]
    }, null, 2),
    output: undefined,
    maxRetries: 2,
    timeout: 1800,
    createdAt: '2026-06-05 07:10',
    updatedAt: '2026-06-05 07:10',
    subtasks: [],
    timeline: [
      { id: 't2-1', time: '07:10:00', status: '已创建', message: '通过新建任务面板手工创建，等待规划拆解中' }
    ]
  },
  {
    id: 'task-3',
    title: '生成周报图表',
    description: '从销售服务器数据库中实时拉取本周高频交易日志，算出波动折线曲率，绘制 SVG 素材。',
    status: 'running',
    priority: 'high',
    agentId: 'code-assistant',
    progress: 80,
    tags: ['代码绘制', 'SVG'],
    input: JSON.stringify({
      log_range: "2026-05-29 to 2026-06-05",
      chart_type: "curved-line",
      output_filename: "sales_volatility.svg"
    }, null, 2),
    output: undefined,
    maxRetries: 3,
    timeout: 1200,
    createdAt: '2026-06-05 04:30',
    updatedAt: '2026-06-05 05:12',
    subtasks: [
      { id: 'sub3-1', title: '拉取远程交易订单记录 SQL查询', status: 'completed', progress: 100 },
      { id: 'sub3-2', title: '编写 Python scipy 代码计算核心曲率', status: 'completed', progress: 100 },
      { id: 'sub3-3', title: '生成 SVG 极简波动图并覆写至 workspace', status: 'running', progress: 40 }
    ],
    timeline: [
      { id: 't3-1', time: '04:30:10', status: '已创建', message: '排班系统自动分发' },
      { id: 't3-2', time: '04:32:00', status: '已规划', message: '代码极客助手分解 3 步计划' },
      { id: 't3-3', time: '04:35:00', status: '执行中', message: '沙箱调配器准备完毕，拉起 STDIO 流，运行 Python 脚本' }
    ]
  },
  {
    id: 'task-4',
    title: '历史去重分析师报表导出 CSV',
    description: '过滤内部 CRM 中过期的分析师重复档案，剔除非业务标签行，导出标准 CSV 文件。',
    status: 'completed',
    priority: 'low',
    agentId: 'data-assistant',
    progress: 100,
    tags: ['数据导出', '清洗'],
    input: JSON.stringify({
      raw_table: "crm_analysts_v4_dirty",
      dedup_by_fields: ["email", "phone"],
      export_path: "/workspace/analysts_clean_0605.csv"
    }, null, 2),
    output: JSON.stringify({
      status: "success",
      output_file: "/workspace/analysts_clean_0605.csv",
      rows_deduped: 481,
      errors_suppressed: 12,
      file_size_bytes: 42100
    }, null, 2),
    maxRetries: 3,
    timeout: 900,
    createdAt: '2026-06-04 15:00',
    updatedAt: '2026-06-04 15:05',
    subtasks: [
      { id: 'sub4-1', title: '多表融合条件查询', status: 'completed', progress: 100 },
      { id: 'sub4-2', title: '分析师名单依据邮箱精准清洗', status: 'completed', progress: 100 },
      { id: 'sub4-3', title: '生成流式 CSV 并写盘', status: 'completed', progress: 100 }
    ],
    timeline: [
      { id: 't4-1', time: '15:00:00', status: '已创建', message: '外部工作流触发' },
      { id: 't4-2', time: '15:01:21', status: '已规划', message: '自动规划完毕' },
      { id: 't4-3', time: '15:02:00', status: '执行中', message: '正在加载 dataset，并计算哈希去重' },
      { id: 't4-4', time: '15:05:00', status: '已完成', message: '成功写入 /workspace/analysts_clean_0605.csv 字节数：42100。' }
    ]
  },
  {
    id: 'task-5',
    title: '代码安全缺陷审计',
    description: '对 src/server 路径之下的动态逻辑，执行依赖包静态弱点检查，列出高危问题。',
    status: 'review',
    priority: 'high',
    agentId: 'code-assistant',
    progress: 100,
    tags: ['代码审计', '安全验证'],
    input: JSON.stringify({
      target_paths: ["./src/server"],
      severity_threshold: "High"
    }, null, 2),
    output: JSON.stringify({
      audit_time: "2026-06-04 14:15:00",
      vulnerabilities_found: [
        { severity: "High", library: "npm/tar", patch: "Use tar>=6.1.9", detail: "Arbitrary file overwrite via directory traversal vulnerabilities" }
      ],
      recommendation: "Please upgrade the tar dependency to avoid potential security risks in file uploads."
    }, null, 2),
    maxRetries: 1,
    timeout: 5000,
    createdAt: '2026-06-04 14:00',
    updatedAt: '2026-06-04 14:22',
    subtasks: [
      { id: 'sub5-1', title: '静态分析 NpmAudit 引擎扫描依赖树', status: 'completed', progress: 100 },
      { id: 'sub5-2', title: '提取 CVE 高危项目并翻译修正方案', status: 'completed', progress: 100 }
    ],
    timeline: [
      { id: 't5-1', time: '14:00:00', status: '已创建', message: '安全漏洞评估需求启动' },
      { id: 't5-2', time: '14:05:00', status: '执行中', message: '依赖包网络解析中...' },
      { id: 't5-3', time: '14:22:00', status: '待审核', message: '输出分析报告完成，当前含有 1 处高危弱点，等待管理员批准处理。' }
    ]
  }
];

export const initialChats: Chat[] = [
  {
    id: 'chat-1',
    agentId: 'data-assistant',
    title: 'Q1 销售数据分析',
    updatedAt: '今天 10:30',
    messages: [
      {
        id: 'msg-1',
        sender: 'user',
        text: '帮我全面分析一下 Q1 的销售数据，包括趋势、异常点、地区分布，最后生成报告。',
        timestamp: '10:00'
      },
      {
        id: 'msg-2',
        sender: 'agent',
        text: '好的，我可以帮您执行这个多阶段的数据分析任务。针对您的销售数据（包含趋势、偏离异常值和区域覆盖），我们需要使用 `data_analysis` 算子，并且搭配 `code_execute` 沙盒仿真脚本来计算精确曲率。这是一个较为复杂的长耗时事务，预计运行需要 10 分钟。为了能在后台安全追踪执行，并且让子任务清晰可见，我强烈提议直接建立一个 **Task 任务**！',
        timestamp: '10:01'
      },
      {
        id: 'msg-3',
        sender: 'system',
        text: '后台自动化 Task 任务已创建。您可以在后台无阻阻塞聊天，系统正在有声有色地流式轮询推进任务！',
        timestamp: '10:02',
        taskCard: {
          taskId: 'task-1',
          title: '分析 Q1 销售数据',
          priority: 'high',
          status: 'running',
          progress: 45,
          subtasks: [
            { id: 'sub-1', title: '下载Q1原始销售数据', status: 'completed', progress: 100 },
            { id: 'sub-2', title: '数据清洗与类型预处理', status: 'completed', progress: 100 },
            { id: 'sub-3', title: '多维度指标趋势分析计算', status: 'running', progress: 30 },
            { id: 'sub-4', title: '生成高分辨率 SVG 可视化图表', status: 'pending', progress: 0 },
            { id: 'sub-5', title: '输出完整的 PDF 商业报告', status: 'pending', progress: 0 }
          ]
        }
      },
      {
        id: 'msg-4',
        sender: 'agent',
        text: '我已经成功在后台为您建立了追踪节点，任务正在运行中。你可以继续和我聊别的话题，或者在任意时间去上方导航的 **📋 Tasks 看板** 中进行可视化排程与状态管理。只要完成后，我会在当前聊天室实时为您推送一份包含完整表格和下载地址的可视化摘要卡片！',
        timestamp: '10:02'
      }
    ]
  },
  {
    id: 'chat-2',
    agentId: 'search-assistant',
    title: '2026 AI 发展趋势',
    updatedAt: '今天 09:15',
    messages: [
      {
        id: 'msg-2-1',
        sender: 'user',
        text: '帮我搜索一下 2026 年 AI 行业的最新发展趋势',
        timestamp: '09:12'
      },
      {
        id: 'msg-2-2',
        sender: 'agent',
        text: '收到，让我进入深度科技搜索引擎，拉取最新的白皮书趋势报告。▍',
        timestamp: '09:12',
        toolCalls: [
          {
            id: 'tc-1',
            name: 'web_search',
            args: JSON.stringify({ query: '2026 AI 行业发展趋势', max_results: 5 }, null, 2),
            status: 'success',
            duration: 2.3,
            result: JSON.stringify([
              { title: "2026年AI行业十大趋势 - 新华网", url: "https://news.cn/2026/01/trend", snippet: "多模态交互和具身智能全面落地，Agent架构成为赋能各行业的核心系统。" },
              { title: "AI Agent 市场爆发式研究报告 - IDC", url: "https://idc.com/reports/2026/agent", snippet: "2026年企业级Agent架构应用渗透率提升，成为重构生产流核心组件。" }
            ], null, 2)
          }
        ]
      },
      {
        id: 'msg-2-3',
        sender: 'agent',
        text: '根据搜索到的最新行业文献，2026 年人工智能领域呈现以下三大关键趋势：\n\n1. **大模型的多模态深度融合**：不再局限于纯文字解答。音画视频的低延迟流式联合生成在大模型端完成，智能体人机交互感体验更真切。\n2. **AI Agent Distributed Architecture（分布式 Agent 架构）**：由传统的单机调用演变为类似 `AgentPlat` 的协管模型。各具专长的小型 Agent 间通过 `MCP 模型上下文协议` 进行技能与资源数据交换，使得单进程的计算限制被打破。\n3. **更底层的环境执行能力**：智能体不仅仅负责撰写文字建议，更能够直接在安全的沙箱管道、甚至本地主机挂载执行工具 and 执行代码生成，达到自主闭环。\n\n需要进一步将此趋势整理为正规报告分析吗？',
        timestamp: '09:15'
      }
    ]
  }
];

export const initialPresetNodes: PresetNode[] = [
  {
    id: 'node-data-clean',
    name: '数据清洗清洗节点',
    description: '过滤缺失值及噪声记录，规范化核心销售列。',
    agentId: 'data-assistant',
    preFilledInput: JSON.stringify({
      clean_rules: "remove_nulls, strip_whitespace",
      target_columns: ["amount", "region", "date"]
    }, null, 2)
  },
  {
    id: 'node-market-search',
    name: '网络市场搜索节点',
    description: '通过互联网抓取最新季度竞品分析及大盘波动指标。',
    agentId: 'search-assistant',
    preFilledInput: JSON.stringify({
      search_term: "2026 Q1 sales competitors",
      depth: 3
    }, null, 2)
  },
  {
    id: 'node-code-render',
    name: 'SVG 报表绘制节点',
    description: '执行沙盒编译，运行 python 脚本自动生成曲率及折线 SVG 素材。',
    agentId: 'code-assistant',
    preFilledInput: JSON.stringify({
      script_path: "/workspace/draw_curvatures.py",
      format: "svg",
      dpi: 300
    }, null, 2)
  },
  {
    id: 'node-pdf-compile',
    name: 'PDF 终审打包节点',
    description: '将清洗好的数据指标和 SVG 报表拼装生成 PDF，完成一键归档。',
    agentId: 'data-assistant',
    preFilledInput: JSON.stringify({
      template: "standard_commercial_v2",
      archival_path: "/workspace/final_pack.pdf"
    }, null, 2)
  }
];

export const initialFlows: Flow[] = [
  {
    id: 'flow-sales-report',
    name: '全自动销售周报发布流',
    description: '串联数据清洗、市场行情抓取、SVG 图表生成与最终 PDF 双轨归档，全流程无缝自动流转。',
    nodes: [
      { nodeId: 'node-data-clean' },
      { nodeId: 'node-market-search' },
      { nodeId: 'node-code-render' },
      { nodeId: 'node-pdf-compile' }
    ],
    createdAt: '2026-06-05'
  }
];

export const initialPermissions: Permission[] = [
  // Agent 模块
  { id: 'agent:create', module: 'Agent', action: 'create', label: '创建 Agent', description: '新建智能代理', enabled: true },
  { id: 'agent:read', module: 'Agent', action: 'read', label: '查看 Agent', description: '查看代理列表和详情', enabled: true },
  { id: 'agent:update', module: 'Agent', action: 'update', label: '编辑 Agent', description: '修改代理配置', enabled: true },
  { id: 'agent:delete', module: 'Agent', action: 'delete', label: '删除 Agent', description: '删除代理实例', enabled: true },
  // Skill 模块
  { id: 'skill:create', module: 'Skill', action: 'create', label: '创建技能', description: '新建技能函数', enabled: true },
  { id: 'skill:read', module: 'Skill', action: 'read', label: '查看技能', description: '查看技能列表', enabled: true },
  { id: 'skill:update', module: 'Skill', action: 'update', label: '编辑技能', description: '修改技能配置', enabled: true },
  { id: 'skill:delete', module: 'Skill', action: 'delete', label: '删除技能', description: '删除技能实例', enabled: true },
  // MCP 模块
  { id: 'mcp:create', module: 'MCP', action: 'create', label: '创建 MCP', description: '新建 MCP 服务', enabled: true },
  { id: 'mcp:read', module: 'MCP', action: 'read', label: '查看 MCP', description: '查看 MCP 连接状态', enabled: true },
  { id: 'mcp:update', module: 'MCP', action: 'update', label: '编辑 MCP', description: '修改 MCP 配置', enabled: true },
  { id: 'mcp:delete', module: 'MCP', action: 'delete', label: '删除 MCP', description: '删除 MCP 连接', enabled: true },
  { id: 'mcp:connect', module: 'MCP', action: 'connect', label: '连接/断开 MCP', description: '切换 MCP 连接状态', enabled: true },
  // Task 模块
  { id: 'task:create', module: 'Task', action: 'create', label: '创建任务', description: '新建任务工单', enabled: true },
  { id: 'task:read', module: 'Task', action: 'read', label: '查看任务', description: '查看任务列表和进度', enabled: true },
  { id: 'task:update', module: 'Task', action: 'update', label: '编辑任务', description: '修改任务参数', enabled: true },
  { id: 'task:delete', module: 'Task', action: 'delete', label: '删除任务', description: '删除任务工单', enabled: true },
  { id: 'task:advance', module: 'Task', action: 'advance', label: '推进任务状态', description: '变更任务执行阶段', enabled: true },
  // Flow 模块
  { id: 'flow:create', module: 'Flow', action: 'create', label: '创建工作流', description: '新建工作流编排', enabled: true },
  { id: 'flow:read', module: 'Flow', action: 'read', label: '查看工作流', description: '查看工作流列表', enabled: true },
  { id: 'flow:update', module: 'Flow', action: 'update', label: '编辑工作流', description: '修改工作流节点', enabled: true },
  { id: 'flow:delete', module: 'Flow', action: 'delete', label: '删除工作流', description: '删除工作流方案', enabled: true },
  { id: 'flow:trigger', module: 'Flow', action: 'trigger', label: '触发工作流', description: '手动执行工作流', enabled: true },
  // Chat 模块
  { id: 'chat:create', module: 'Chat', action: 'create', label: '创建对话', description: '发起新对话', enabled: true },
  { id: 'chat:read', module: 'Chat', action: 'read', label: '查看对话', description: '查看对话历史', enabled: true },
  { id: 'chat:delete', module: 'Chat', action: 'delete', label: '删除对话', description: '删除对话记录', enabled: true },
  // 系统管理
  { id: 'system:user_manage', module: '系统', action: 'manage', label: '用户管理', description: '管理系统用户', enabled: true },
  { id: 'system:role_manage', module: '系统', action: 'manage', label: '角色管理', description: '管理系统角色', enabled: true },
  { id: 'system:perm_manage', module: '系统', action: 'manage', label: '权限管理', description: '管理系统权限', enabled: true },
];

export const initialRoles: Role[] = [
  {
    id: 'role-admin',
    name: '超级管理员',
    code: 'admin',
    description: '拥有系统全部权限，可管理所有模块和用户',
    permissionIds: initialPermissions.map(p => p.id),
    isSystem: true,
    createdAt: '2026-01-01',
  },
  {
    id: 'role-editor',
    name: '编辑者',
    code: 'editor',
    description: '可创建和编辑 Agent、Skill、MCP、Task、Flow，不可删除或管理系统',
    permissionIds: [
      'agent:create', 'agent:read', 'agent:update',
      'skill:create', 'skill:read', 'skill:update',
      'mcp:create', 'mcp:read', 'mcp:update', 'mcp:connect',
      'task:create', 'task:read', 'task:update', 'task:advance',
      'flow:create', 'flow:read', 'flow:update', 'flow:trigger',
      'chat:create', 'chat:read',
    ],
    isSystem: true,
    createdAt: '2026-01-01',
  },
  {
    id: 'role-viewer',
    name: '观察者',
    code: 'viewer',
    description: '仅拥有只读权限，可查看所有模块但不能修改',
    permissionIds: [
      'agent:read', 'skill:read', 'mcp:read',
      'task:read', 'flow:read', 'chat:read',
    ],
    isSystem: false,
    createdAt: '2026-01-15',
  },
];

export const initialUsers: User[] = [
  {
    id: 'user-admin',
    username: 'admin',
    email: 'admin@agentplat.dev',
    password: 'admin123',
    phone: '138-0000-0001',
    department: '技术部',
    bio: '系统超级管理员，负责平台整体运维与配置管理。',
    status: 'active',
    roleIds: ['role-admin'],
    createdAt: '2026-01-01',
    lastLoginAt: '2026-06-11 09:30',
  },
  {
    id: 'user-editor',
    username: 'zhangsan',
    email: 'zhangsan@agentplat.dev',
    password: '123456',
    phone: '138-0000-0002',
    department: '数据部',
    bio: '数据分析师，负责销售数据清洗和报告生成。',
    status: 'active',
    roleIds: ['role-editor'],
    createdAt: '2026-03-15',
    lastLoginAt: '2026-06-10 14:20',
  },
  {
    id: 'user-viewer',
    username: 'lisi',
    email: 'lisi@agentplat.dev',
    password: '123456',
    phone: '138-0000-0003',
    department: '产品部',
    bio: '产品经理，主要查看平台运营数据和任务执行情况。',
    status: 'active',
    roleIds: ['role-viewer'],
    createdAt: '2026-04-01',
    lastLoginAt: '2026-06-09 16:45',
  },
  {
    id: 'user-inactive',
    username: 'wangwu',
    email: 'wangwu@agentplat.dev',
    password: '123456',
    phone: '138-0000-0004',
    department: '市场部',
    bio: '市场运营专员，账号已停用。',
    status: 'inactive',
    roleIds: ['role-editor'],
    createdAt: '2026-02-20',
  },
];

