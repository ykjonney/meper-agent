/**
 * Design System Page — comprehensive theme showcase.
 *
 * Renders ALL components so users can preview and switch themes.
 * Theme changes here propagate globally via ThemeContext.
 */
import { useState } from 'react'
import {
  Button, Tag, Avatar, Badge, Progress, Switch, Select, Card, Table, Tabs, Dropdown,
  Tooltip, Alert, Empty, Spin, Divider, Descriptions, Collapse, Pagination, Steps, Timeline,
  Checkbox, Radio, InputNumber, DatePicker, Slider, Rate, Result, Modal, Popover,
  Breadcrumb, Typography, Space, Input,
} from 'antd'
import {
  NodeIndexOutlined, CheckOutlined, PlusOutlined, StarOutlined, BellOutlined,
  UserOutlined, RobotOutlined, BranchesOutlined, ThunderboltOutlined, CheckCircleOutlined,
  ArrowUpOutlined, ArrowDownOutlined, SearchOutlined, DownloadOutlined, FilterOutlined,
  MoreOutlined, SettingOutlined, KeyOutlined, DeleteOutlined, EditOutlined,
  InfoCircleOutlined, ExclamationCircleOutlined, CloseCircleOutlined,
  DownOutlined, LeftOutlined, RightOutlined, ReloadOutlined,
  ClockCircleOutlined, FileTextOutlined, LinkOutlined,
  HomeOutlined, TeamOutlined, ToolOutlined, DatabaseOutlined, WechatOutlined,
  SmileOutlined, LoadingOutlined, SendOutlined,
} from '@ant-design/icons'
import { useTheme, THEMES } from '../contexts/ThemeContext'

const { Text, Title } = Typography
const { TextArea } = Input

export default function DesignSystemPage() {
  const { t, setTheme } = useTheme()
  const [modalOpen, setModalOpen] = useState(false)
  const [tabKey, setTabKey] = useState('tab1')

  const STATUSES = [
    { label: '运行中', color: '#2563EB', bg: '#EFF6FF' },
    { label: '成功', color: '#10B981', bg: '#D1FAE5' },
    { label: '警告', color: '#F59E0B', bg: '#FEF3C7' },
    { label: '失败', color: '#EF4444', bg: '#FEE2E2' },
    { label: '草稿', color: '#94A3B8', bg: '#F1F5F9' },
  ]

  const TABLE_COLUMNS = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '模型', dataIndex: 'model', key: 'model' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (s: string) => {
      const st = STATUSES.find(x => x.label === s) || STATUSES[4]
      return <Tag className="!m-0 !px-2 !py-0.5 !text-xs !rounded" style={{ color: st.color, background: st.bg, borderColor: 'transparent' }}>{s}</Tag>
    }},
    { title: '操作', key: 'action', render: () => <Button type="link" size="small" icon={<EditOutlined />}>编辑</Button> },
  ]

  const TABLE_DATA = [
    { key: '1', name: '数据分析 Agent', model: 'GPT-4', status: '运行中' },
    { key: '2', name: '客户支持 Bot', model: 'Claude 3', status: '成功' },
    { key: '3', name: '代码审查 Agent', model: 'Gemini', status: '警告' },
    { key: '4', name: '数据同步任务', model: 'GPT-4', status: '失败' },
  ]

  const STEPS = [
    { title: '需求', description: '收集需求' },
    { title: '设计', description: '架构设计' },
    { title: '开发', description: '编码实现' },
    { title: '部署', description: '上线发布' },
  ]

  return (
    <div className="min-h-screen bg-[#F8FAFC]">
      <div className="max-w-6xl mx-auto p-8">
        {/* ═══ Header ═══ */}
        <div className="flex items-center gap-4 mb-8">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center text-white" style={{ background: t.primary }}>
            <NodeIndexOutlined />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[#0F172A] m-0">Agent Flow 设计系统</h1>
            <p className="text-sm text-[#64748B] m-0 mt-0.5">主题预览 · 所有组件实时切换 · 当前主题: <span style={{ color: t.primary }}>{t.zhName}</span></p>
          </div>
        </div>

        {/* ═══ Theme Picker ═══ */}
        <div className="rounded-xl border border-gray-200 bg-white p-6 mb-8">
          <div className="text-sm font-semibold text-[#0F172A] mb-4">选择主题色</div>
          <div className="flex flex-wrap gap-3">
            {THEMES.map((theme) => {
              const isActive = t.key === theme.key
              return (
                <button
                  key={theme.key}
                  onClick={() => setTheme(theme)}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 cursor-pointer border ${
                    isActive ? 'text-white shadow-sm' : 'border-gray-200 text-[#475569] hover:border-gray-300 bg-white'
                  }`}
                  style={isActive ? { background: theme.primary, borderColor: theme.primary } : undefined}
                >
                  <span className="w-3.5 h-3.5 rounded-full shrink-0" style={{ background: theme.primary }} />
                  {theme.zhName}
                  {isActive && <CheckOutlined className="text-[10px]" />}
                </button>
              )
            })}
          </div>
        </div>

        {/* ════════════════════════════════════════════════════════
            COMPONENT SHOWCASE
           ════════════════════════════════════════════════════════ */}
        <div className="space-y-8">

          {/* ── 1. Typography ── */}
          <section>
            <h2 className="text-sm font-semibold text-[#0F172A] mb-3">排版 Typography</h2>
            <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-3">
              <Title level={1} style={{ margin: 0 }}>h1. 标题一 (32px)</Title>
              <Title level={2} style={{ margin: 0 }}>h2. 标题二 (28px)</Title>
              <Title level={3} style={{ margin: 0 }}>h3. 标题三 (24px)</Title>
              <Title level={4} style={{ margin: 0 }}>h4. 标题四 (20px)</Title>
              <Divider className="!my-2" />
              <Text>正文文本 — DM Sans, 14px, #0F172A</Text>
              <br />
              <Text type="secondary">次要文本 — #475569</Text>
              <br />
              <Text type="tertiary" style={{ color: '#94A3B8' }}>辅助文本 — #94A3B8</Text>
              <br />
              <Text code>console.log("行内代码")</Text>
              <Text keyboard>⌘K</Text>
              <Text mark>标记文本</Text>
              <Text strong>加粗文本</Text>
              <br />
              <span className="mono text-xs text-[#475569] font-mono">Monospace — JetBrains Mono, 代码块专用</span>
            </div>
          </section>

          {/* ── 2. Stat Cards ── */}
          <section>
            <h2 className="text-sm font-semibold text-[#0F172A] mb-3">统计卡片 Stat Card</h2>
            <div className="grid grid-cols-4 gap-4">
              {[
                { title: '活跃 Agent', value: '12', icon: <RobotOutlined />, change: '+3', up: true },
                { title: '运行工作流', value: '8', icon: <BranchesOutlined />, change: '+2', up: true },
                { title: '今日执行', value: '156', icon: <ThunderboltOutlined />, change: '+12%', up: true },
                { title: '成功率', value: '98.5%', icon: <CheckCircleOutlined />, change: '-0.3%', up: false },
              ].map((stat) => (
                <div key={stat.title} className="rounded-xl border border-gray-200 bg-white p-5">
                  <div className="flex items-start justify-between mb-3">
                    <div className="w-10 h-10 rounded-lg flex items-center justify-center text-base" style={{ background: t.bg, color: t.primary }}>
                      {stat.icon}
                    </div>
                    <span className={`text-xs font-medium inline-flex items-center gap-0.5 ${stat.up ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                      {stat.up ? <ArrowUpOutlined /> : <ArrowDownOutlined />}{stat.change}
                    </span>
                  </div>
                  <div className="text-2xl font-semibold text-[#0F172A] mb-0.5">{stat.value}</div>
                  <div className="text-xs text-[#64748B]">{stat.title}</div>
                </div>
              ))}
            </div>
          </section>

          {/* ── 3. Buttons ── */}
          <section>
            <h2 className="text-sm font-semibold text-[#0F172A] mb-3">按钮 Button</h2>
            <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
              <div className="flex items-center gap-3 flex-wrap">
                <Button type="primary" icon={<PlusOutlined />}>Primary</Button>
                <Button>Default</Button>
                <Button type="dashed">Dashed</Button>
                <Button type="text">Text</Button>
                <Button type="link">Link</Button>
                <Button type="primary" danger icon={<DeleteOutlined />}>Danger</Button>
                <Button type="primary" size="large" icon={<StarOutlined />}>Large</Button>
                <Button type="primary" size="small">Small</Button>
              </div>
              <Divider className="!my-1" />
              <div className="flex items-center gap-3 flex-wrap">
                <Button shape="circle" type="primary" icon={<SearchOutlined />} />
                <Button shape="round" type="primary" icon={<PlusOutlined />}>Round</Button>
                <Button icon={<DownloadOutlined />}>导出</Button>
                <Button icon={<FilterOutlined />}>筛选</Button>
                <Button type="primary" loading icon={<SendOutlined />}>加载中</Button>
                <Button type="primary" ghost>Ghost</Button>
              </div>
            </div>
          </section>

          {/* ── 4. Tags & Progress ── */}
          <section>
            <h2 className="text-sm font-semibold text-[#0F172A] mb-3">标签 Tag & 进度 Progress</h2>
            <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
              <div className="flex items-center gap-2 flex-wrap">
                <Tag color={t.primary}>Primary</Tag>
                <Tag color="#10B981">成功</Tag>
                <Tag color="#F59E0B">警告</Tag>
                <Tag color="#EF4444">错误</Tag>
                <Tag>Default</Tag>
                <Tag closable color={t.primary}>可关闭</Tag>
                <Tag icon={<CheckCircleOutlined />} color="success">成功</Tag>
                <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>
              </div>
              <Divider className="!my-1" />
              <div className="space-y-2">
                <Progress percent={45} size="small" strokeColor={t.primary} railColor="#F1F5F9" />
                <Progress percent={72} size="small" strokeColor={t.primary} railColor="#F1F5F9" />
                <Progress percent={90} size="small" strokeColor="#10B981" railColor="#F1F5F9" />
                <Progress percent={100} size="small" strokeColor="#10B981" railColor="#F1F5F9" format={() => '完成'} />
              </div>
              <Divider className="!my-1" />
              <div className="flex items-center gap-3 flex-wrap">
                <div className="text-xs text-[#64748B]">环形进度:</div>
                <Progress type="circle" percent={75} size={48} strokeColor={t.primary} railColor="#F1F5F9" />
                <Progress type="circle" percent={100} size={48} strokeColor="#10B981" railColor="#F1F5F9" />
                <Progress type="circle" percent={45} size={48} strokeColor={t.light} railColor="#F1F5F9" />
              </div>
            </div>
          </section>

          {/* ── 5. Data Display ── */}
          <section>
            <h2 className="text-sm font-semibold text-[#0F172A] mb-3">数据展示 Data Display</h2>
            <div className="grid grid-cols-2 gap-4">

              {/* Card */}
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-3">Card 卡片</h3>
                <div className="space-y-3">
                  <Card title="基础卡片" size="small" style={{ borderRadius: 10 }}>
                    <p className="text-sm text-[#475569] m-0">卡片内容，展示信息区块</p>
                  </Card>
                  <Card
                    size="small"
                    actions={[<SettingOutlined key="setting" />, <EditOutlined key="edit" />, <MoreOutlined key="more" />]}
                    style={{ borderRadius: 10 }}
                  >
                    <Card.Meta
                      avatar={<Avatar icon={<UserOutlined />} style={{ background: t.primary }} />}
                      title="带操作卡片"
                      description="底部有操作栏"
                    />
                  </Card>
                </div>
              </div>

              {/* Table */}
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-3">Table 表格</h3>
                <Table columns={TABLE_COLUMNS} dataSource={TABLE_DATA} pagination={false} size="small" />
              </div>

              {/* Tabs */}
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-3">Tabs 标签页</h3>
                <Tabs
                  activeKey={tabKey}
                  onChange={setTabKey}
                  items={[
                    { key: 'tab1', label: 'Agent', children: <div className="text-sm text-[#475569] py-2">Agent 配置与管理</div> },
                    { key: 'tab2', label: '工作流', children: <div className="text-sm text-[#475569] py-2">工作流编排与监控</div> },
                    { key: 'tab3', label: '工具', children: <div className="text-sm text-[#475569] py-2">工具注册与调用</div> },
                  ]}
                />
              </div>

              {/* Descriptions */}
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-3">Descriptions 描述列表</h3>
                <Descriptions size="small" column={1} colon={false}>
                  <Descriptions.Item label="名称">数据分析 Agent</Descriptions.Item>
                  <Descriptions.Item label="模型">GPT-4</Descriptions.Item>
                  <Descriptions.Item label="状态"><Tag color={t.primary}>运行中</Tag></Descriptions.Item>
                  <Descriptions.Item label="创建时间">2026-03-15</Descriptions.Item>
                </Descriptions>
              </div>

              {/* Collapse */}
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-3">Collapse 折叠面板</h3>
                <Collapse
                  size="small"
                  items={[
                    { key: '1', label: '执行日志', children: <div className="text-sm text-[#475569]">[2026-06-09 10:32] 任务开始执行...</div> },
                    { key: '2', label: '详细配置', children: <div className="text-sm text-[#475569]">model: gpt-4, temperature: 0.7, max_tokens: 2048</div> },
                  ]}
                />
              </div>

              {/* Timeline */}
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-3">Timeline 时间线</h3>
                <Timeline
                  items={[
                    { color: t.primary, content: <div className="text-xs"><span className="font-medium">部署上线</span><div className="text-[#94A3B8]">5 分钟前</div></div> },
                    { color: '#10B981', content: <div className="text-xs"><span className="font-medium">测试通过</span><div className="text-[#94A3B8]">30 分钟前</div></div> },
                    { color: '#F59E0B', content: <div className="text-xs"><span className="font-medium">代码审查</span><div className="text-[#94A3B8]">2 小时前</div></div> },
                    { color: '#94A3B8', content: <div className="text-xs"><span className="font-medium">开始开发</span><div className="text-[#94A3B8]">1 天前</div></div> },
                  ]}
                />
              </div>

            </div>
          </section>

          {/* ── 6. Feedback ── */}
          <section>
            <h2 className="text-sm font-semibold text-[#0F172A] mb-3">反馈 Feedback</h2>
            <div className="grid grid-cols-2 gap-4">

              {/* Alert */}
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-3">Alert 警告提示</h3>
                <div className="space-y-2">
                  <Alert title="操作成功" type="success" showIcon closable />
                  <Alert title="信息提示" description="这是一条带描述的提示信息" type="info" showIcon />
                  <Alert title="警告消息" type="warning" showIcon />
                  <Alert title="错误消息" type="error" showIcon />
                </div>
              </div>

              {/* Modal + Tooltip + Popover */}
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-3">Modal / Tooltip / Popover</h3>
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <Button type="primary" onClick={() => setModalOpen(true)}>打开弹窗</Button>
                    <Tooltip title="这是提示信息">
                      <Button icon={<InfoCircleOutlined />}>悬浮提示</Button>
                    </Tooltip>
                    <Popover content="这是气泡卡片的内容" title="标题">
                      <Button icon={<ExclamationCircleOutlined />}>气泡</Button>
                    </Popover>
                  </div>
                  <Modal
                    title="确认操作"
                    open={modalOpen}
                    onCancel={() => setModalOpen(false)}
                    onOk={() => setModalOpen(false)}
                    destroyOnHidden
                  >
                    <p className="text-sm text-[#475569]">确定要执行此操作吗？</p>
                  </Modal>

                  <Divider className="!my-2" />

                  <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-2">Spin / Empty / Result</h3>
                  <div className="flex items-center gap-4 flex-wrap">
                    <Spin size="small" />
                    <Spin />
                    <Spin indicator={<LoadingOutlined />} />
                    <div className="flex items-center gap-2 text-sm text-[#64748B]">
                      <Spin size="small" /> 加载中...
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />
                    <Result status="success" title="操作成功" subTitle="任务已完成" />
                  </div>
                </div>
              </div>

            </div>
          </section>

          {/* ── 7. Navigation ── */}
          <section>
            <h2 className="text-sm font-semibold text-[#0F172A] mb-3">导航 Navigation</h2>
            <div className="grid grid-cols-2 gap-4">

              {/* Steps */}
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-3">Steps 步骤条</h3>
                <Steps
                  current={1}
                  size="small"
                  items={STEPS.map(s => ({ title: s.title, content: s.description }))}
                />
                <Divider className="!my-3" />
                <Steps
                  current={2}
                  size="small"
                  orientation="vertical"
                  items={STEPS.map(s => ({ title: s.title, content: s.description }))}
                />
              </div>

              {/* Dropdown + Breadcrumb + Pagination */}
              <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
                <div>
                  <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-3">Breadcrumb 面包屑</h3>
                  <Breadcrumb
                    items={[
                      { title: <><HomeOutlined /> 首页</> },
                      { title: <><BranchesOutlined /> 工作流</> },
                      { title: '数据分析' },
                    ]}
                  />
                </div>

                <Divider className="!my-2" />

                <div>
                  <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-3">Dropdown 下拉菜单</h3>
                  <Dropdown menu={{
                    items: [
                      { key: '1', label: '编辑', icon: <EditOutlined /> },
                      { key: '2', label: '复制', icon: <FileTextOutlined /> },
                      { type: 'divider' },
                      { key: '3', label: '删除', icon: <DeleteOutlined />, danger: true },
                    ],
                  }}>
                    <Button>更多操作 <DownOutlined /></Button>
                  </Dropdown>
                </div>

                <Divider className="!my-2" />

                <div>
                  <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-3">Pagination 分页</h3>
                  <Pagination defaultCurrent={1} total={50} size="small" showSizeChanger={false} />
                  <div className="mt-2">
                    <Pagination defaultCurrent={1} total={200} size="small" showTotal={(t) => `共 ${t} 条`} showSizeChanger={false} />
                  </div>
                </div>
              </div>

            </div>
          </section>

          {/* ── 8. Form Elements (Extended) ── */}
          <section>
            <h2 className="text-sm font-semibold text-[#0F172A] mb-3">表单元素 Form</h2>
            <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-5">
              {/* Row 1: Basic inputs */}
              <div className="flex items-center gap-6 flex-wrap">
                <div>
                  <div className="text-xs text-[#64748B] mb-1">文本输入</div>
                  <Input placeholder="输入内容..." style={{ width: 200 }} />
                </div>
                <div>
                  <div className="text-xs text-[#64748B] mb-1">文本域</div>
                  <TextArea placeholder="多行文本..." rows={2} style={{ width: 200 }} />
                </div>
                <div>
                  <div className="text-xs text-[#64748B] mb-1">数字输入</div>
                  <InputNumber min={1} max={100} defaultValue={50} />
                </div>
              </div>

              {/* Row 2: Select & Switch */}
              <div className="flex items-center gap-6 flex-wrap">
                <div>
                  <div className="text-xs text-[#64748B] mb-1">下拉选择</div>
                  <Select value="GPT-4" style={{ width: 120 }} options={[
                    { value: 'GPT-4', label: 'GPT-4' },
                    { value: 'Claude', label: 'Claude' },
                    { value: 'Gemini', label: 'Gemini' },
                  ]} />
                </div>
                <div>
                  <div className="text-xs text-[#64748B] mb-1">开关</div>
                  <Switch defaultChecked style={{ background: t.primary }} />
                </div>
                <div>
                  <div className="text-xs text-[#64748B] mb-1">评分</div>
                  <Rate defaultValue={3.5} allowHalf />
                </div>
                <div>
                  <div className="text-xs text-[#64748B] mb-1">滑块</div>
                  <Slider defaultValue={60} style={{ width: 160 }} />
                </div>
              </div>

              {/* Row 3: Checkbox & Radio & DatePicker */}
              <div className="flex items-center gap-6 flex-wrap">
                <div>
                  <div className="text-xs text-[#64748B] mb-1">复选框</div>
                  <Space orientation="vertical" size={2}>
                    <Checkbox checked>GPT-4</Checkbox>
                    <Checkbox>Claude 3</Checkbox>
                    <Checkbox disabled>Gemini</Checkbox>
                  </Space>
                </div>
                <div>
                  <div className="text-xs text-[#64748B] mb-1">单选框</div>
                  <Radio.Group defaultValue="a" size="small">
                    <Radio.Button value="a">全部</Radio.Button>
                    <Radio.Button value="b">运行中</Radio.Button>
                    <Radio.Button value="c">已完成</Radio.Button>
                  </Radio.Group>
                  <div className="mt-2 space-y-1">
                    <Radio defaultChecked>启用通知</Radio>
                    <Radio>关闭通知</Radio>
                  </div>
                </div>
                <div>
                  <div className="text-xs text-[#64748B] mb-1">日期选择</div>
                  <DatePicker />
                </div>
              </div>

              {/* Badge */}
              <div className="flex items-center gap-4 flex-wrap">
                <div>
                  <div className="text-xs text-[#64748B] mb-1">徽标 Badge</div>
                  <div className="flex items-center gap-4">
                    <Badge count={5} color={t.primary}>
                      <Button icon={<BellOutlined />} />
                    </Badge>
                    <Badge count={0} showZero color="#F59E0B">
                      <Button icon={<BellOutlined />} />
                    </Badge>
                    <Badge dot color="#EF4444">
                      <Button icon={<BellOutlined />} />
                    </Badge>
                    <span className="text-sm text-[#64748B]">
                      <Badge status="success" /> 在线
                    </span>
                    <span className="text-sm text-[#64748B]">
                      <Badge status="error" /> 离线
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* ── 9. Avatar ── */}
          <section>
            <h2 className="text-sm font-semibold text-[#0F172A] mb-3">头像 Avatar</h2>
            <div className="rounded-xl border border-gray-200 bg-white p-5 flex items-center gap-4">
              <Avatar size={40} icon={<UserOutlined />} style={{ background: t.primary }} />
              <Avatar size={32} icon={<UserOutlined />} style={{ background: t.bg, color: t.primary }} />
              <Avatar size={24} style={{ background: t.primary }}>A</Avatar>
              <Avatar size={40} style={{ background: '#10B981' }}>U</Avatar>
              <Avatar size={40} style={{ background: '#F59E0B' }}>K</Avatar>
              <Avatar size={40} style={{ background: '#EF4444' }}>E</Avatar>
              <Avatar size={28} icon={<UserOutlined />} style={{ background: t.light }} />
              <Avatar shape="square" size={40} icon={<UserOutlined />} style={{ background: t.primary }} />
            </div>
          </section>

          {/* ── 10. Status Tags ── */}
          <section>
            <h2 className="text-sm font-semibold text-[#0F172A] mb-3">语义状态 Status</h2>
            <div className="rounded-xl border border-gray-200 bg-white p-5 flex items-center gap-3 flex-wrap">
              {STATUSES.map((s) => (
                <Tag key={s.label} className="!inline-flex !items-center !gap-1 !px-3 !py-1 !text-xs !rounded-lg" style={{ color: s.color, background: s.bg, borderColor: 'transparent' }}>
                  {s.label}
                </Tag>
              ))}
            </div>
          </section>

          {/* ── 11. Charts ── */}
          <section>
            <h2 className="text-sm font-semibold text-[#0F172A] mb-3">图表 Charts (纯 CSS/SVG)</h2>
            <div className="grid grid-cols-3 gap-4">

              {/* Bar Chart */}
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-4">柱状图</h3>
                <div className="flex items-end justify-between gap-2 h-32">
                  {[
                    { label: 'Mon', value: 65 },
                    { label: 'Tue', value: 45 },
                    { label: 'Wed', value: 80 },
                    { label: 'Thu', value: 55 },
                    { label: 'Fri', value: 90 },
                    { label: 'Sat', value: 40 },
                    { label: 'Sun', value: 30 },
                  ].map((b) => (
                    <div key={b.label} className="flex flex-col items-center gap-1 flex-1">
                      <div className="w-full rounded-t-sm transition-all duration-500" style={{ height: `${b.value}%`, background: b.value > 75 ? t.primary : b.value > 50 ? t.light : '#E2E8F0', opacity: 0.85 }} />
                      <span className="text-[10px] text-[#94A3B8]">{b.label}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Line Chart (SVG) */}
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-4">折线图</h3>
                <svg viewBox="0 0 200 100" className="w-full h-32">
                  <defs>
                    <linearGradient id="lineGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={t.primary} stopOpacity="0.25" />
                      <stop offset="100%" stopColor={t.primary} stopOpacity="0.02" />
                    </linearGradient>
                  </defs>
                  <polyline
                    fill="none"
                    stroke={t.primary}
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    points="10,80 35,55 60,70 85,30 110,45 135,20 160,50 190,15"
                  />
                  <polygon
                    fill="url(#lineGrad)"
                    points="10,80 35,55 60,70 85,30 110,45 135,20 160,50 190,15 190,100 10,100"
                  />
                  {[
                    [10, 80], [35, 55], [60, 70], [85, 30], [110, 45], [135, 20], [160, 50], [190, 15],
                  ].map(([x, y], i) => (
                    <circle key={i} cx={x} cy={y} r="3" fill="white" stroke={t.primary} strokeWidth="2" />
                  ))}
                </svg>
                <div className="flex justify-between text-[10px] text-[#94A3B8] mt-1">
                  <span>1月</span><span>3月</span><span>5月</span><span>7月</span>
                </div>
              </div>

              {/* Donut Chart (SVG) */}
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h3 className="text-xs font-semibold text-[#94A3B8] uppercase tracking-wider mb-4">环形图</h3>
                <div className="flex flex-col items-center">
                  <svg viewBox="0 0 100 100" className="w-28 h-28 -rotate-90">
                    <circle cx="50" cy="50" r="40" fill="none" stroke="#F1F5F9" strokeWidth="10" />
                    <circle cx="50" cy="50" r="40" fill="none" stroke={t.primary} strokeWidth="10"
                      strokeDasharray={`${60 * 2.513} ${40 * 2.513}`}
                      strokeLinecap="round"
                    />
                    <circle cx="50" cy="50" r="40" fill="none" stroke="#10B981" strokeWidth="10"
                      strokeDasharray={`${25 * 2.513} ${75 * 2.513}`}
                      strokeDashoffset={`-${60 * 2.513}`}
                      strokeLinecap="round"
                    />
                    <circle cx="50" cy="50" r="40" fill="none" stroke="#F59E0B" strokeWidth="10"
                      strokeDasharray={`${15 * 2.513} ${85 * 2.513}`}
                      strokeDashoffset={`-${85 * 2.513}`}
                      strokeLinecap="round"
                    />
                  </svg>
                  <div className="flex items-center gap-3 mt-2 text-xs">
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: t.primary }} /> GPT-4 60%</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: '#10B981' }} /> Claude 25%</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: '#F59E0B' }} /> 其他 15%</span>
                  </div>
                </div>
              </div>

            </div>
          </section>

        </div>

        {/* ═══ Footer ═══ */}
        <div className="mt-12 pt-6 border-t border-gray-100 text-center text-xs text-[#94A3B8]">
          Agent Flow Design System · 当前主题: <span style={{ color: t.primary }}>{t.zhName}</span> · {t.vibe} · 共 11 个分类展示
        </div>
      </div>
    </div>
  )
}

export { DesignSystemPage }
