import React, { useState } from 'react';
import { useAppState } from '../AppContext';
import { User } from '../types';
import { useTheme } from '../ThemeContext';
import { useTranslation } from '../LocaleContext';
import {
  Plus, Search, User as UserIcon, Building2, Calendar, Mail, Phone
} from 'lucide-react';
import {
  Table, Tag, Button, Input, Select, Space, Modal, Form,
  Avatar, Tooltip, Empty, Typography, Popconfirm, message, Card
} from 'antd';
import {
  PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined,
  UserOutlined, MailOutlined, PhoneOutlined, LockOutlined,
  BankOutlined, CalendarOutlined
} from '@ant-design/icons';
import { ResizableModal } from './ResizableModal';

const { TextArea } = Input;
const { Title, Text } = Typography;

export const UsersPage: React.FC = () => {
  const { users, roles, addUser, updateUser, deleteUser } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();

  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [roleFilter, setRoleFilter] = useState<string>('all');
  const [modalOpen, setModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [form] = Form.useForm();

  const filteredUsers = users.filter(u => {
    const matchSearch = u.username.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        u.email.toLowerCase().includes(searchQuery.toLowerCase());
    const matchStatus = statusFilter === 'all' || u.status === statusFilter;
    const matchRole = roleFilter === 'all' || u.roleIds.includes(roleFilter);
    return matchSearch && matchStatus && matchRole;
  });

  const getStatusColor = (status: User['status']): string => {
    switch (status) {
      case 'active': return 'green';
      case 'inactive': return 'default';
      case 'locked': return 'red';
    }
  };

  const getStatusLabel = (status: User['status']) => {
    switch (status) {
      case 'active': return t('users.statusActive');
      case 'inactive': return t('users.statusInactive');
      case 'locked': return t('users.statusLocked');
    }
  };

  const getAvatarColor = (name: string) => {
    const colors = ['#1677ff', '#52c41a', '#faad14', '#f5222d', '#722ed1', '#13c2c2', '#eb2f96'];
    let hash = 0;
    for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
    return colors[Math.abs(hash) % colors.length];
  };

  const handleOpenCreate = () => {
    setEditingUser(null);
    form.resetFields();
    form.setFieldsValue({ status: 'active', roleIds: [] });
    setModalOpen(true);
  };

  const handleOpenEdit = (user: User) => {
    setEditingUser(user);
    form.setFieldsValue({
      username: user.username,
      email: user.email,
      password: '',
      phone: user.phone || '',
      department: user.department || '',
      bio: user.bio || '',
      status: user.status,
      roleIds: user.roleIds,
    });
    setModalOpen(true);
  };

  const handleSubmit = () => {
    form.validateFields().then(values => {
      if (editingUser) {
        updateUser({
          ...editingUser,
          username: values.username.trim(),
          email: values.email.trim(),
          password: values.password || editingUser.password,
          phone: values.phone || undefined,
          department: values.department || undefined,
          bio: values.bio || undefined,
          status: values.status,
          roleIds: values.roleIds,
        });
        message.success(t('users.userUpdated'));
      } else {
        addUser({
          username: values.username.trim(),
          email: values.email.trim(),
          password: values.password,
          phone: values.phone || undefined,
          department: values.department || undefined,
          bio: values.bio || undefined,
          status: values.status,
          roleIds: values.roleIds,
          lastLoginAt: undefined,
        });
        message.success(t('users.userCreated'));
      }
      setModalOpen(false);
    });
  };

  const handleDelete = (id: string) => {
    deleteUser(id);
    message.success(t('users.userDeleted'));
  };

  const columns = [
    {
      title: t('users.columnUser'),
      key: 'user',
      render: (_: unknown, record: User) => (
        <div className="flex items-center gap-3">
          <Avatar style={{ backgroundColor: getAvatarColor(record.username) }}>
            {record.username.slice(0, 1).toUpperCase()}
          </Avatar>
          <div>
            <div className="font-semibold text-sm">{record.username}</div>
            <Text type="secondary" className="text-xs flex items-center gap-1">
              <Mail className="h-3 w-3" />
              {record.email}
            </Text>
          </div>
        </div>
      ),
    },
    {
      title: t('users.columnStatus'),
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: User['status']) => (
        <Tag color={getStatusColor(status)}>{getStatusLabel(status)}</Tag>
      ),
    },
    {
      title: t('users.columnRoles'),
      dataIndex: 'roleIds',
      key: 'roleIds',
      width: 200,
      render: (roleIds: string[]) => (
        <Space size={[4, 4]} wrap>
          {roleIds.map(rid => {
            const role = roles.find(r => r.id === rid);
            return role ? <Tag key={rid} color="blue">{role.name}</Tag> : null;
          })}
        </Space>
      ),
    },
    {
      title: t('users.columnDepartment'),
      dataIndex: 'department',
      key: 'department',
      width: 120,
      render: (text: string) => text ? (
        <span className="flex items-center gap-1 text-xs">
          <Building2 className="h-3 w-3" />
          {text}
        </span>
      ) : <Text type="secondary" className="text-xs">-</Text>,
    },
    {
      title: t('users.columnPhone'),
      dataIndex: 'phone',
      key: 'phone',
      width: 130,
      render: (text: string) => text ? (
        <span className="flex items-center gap-1 text-xs">
          <Phone className="h-3 w-3" />
          {text}
        </span>
      ) : <Text type="secondary" className="text-xs">-</Text>,
    },
    {
      title: t('users.columnCreatedAt'),
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 110,
      render: (text: string) => (
        <Text type="secondary" className="text-xs flex items-center gap-1">
          <Calendar className="h-3 w-3" />
          {text}
        </Text>
      ),
    },
    {
      title: t('users.columnActions'),
      key: 'actions',
      width: 130,
      render: (_: unknown, record: User) => (
        <Space size={4}>
          <Tooltip title={t('users.editTooltip')}>
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleOpenEdit(record)}
            />
          </Tooltip>
          <Popconfirm
            title={t('users.confirmDelete').replace('{name}', record.username)}
            onConfirm={() => handleDelete(record.id)}
            okText={t('users.okText')}
            cancelText={t('users.cancelText')}
          >
            <Tooltip title={t('users.deleteTooltip')}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className="px-4 py-6">
      <Card size="small">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="flex flex-wrap items-center gap-3">
            <Input
              prefix={<SearchOutlined />}
              placeholder={t('users.searchPlaceholder')}
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={{ width: 200 }}
              allowClear
            />
            <Select
              value={statusFilter}
              onChange={setStatusFilter}
              style={{ width: 120 }}
              options={[
                { label: t('users.allStatus'), value: 'all' },
                { label: t('users.statusActive'), value: 'active' },
                { label: t('users.statusInactive'), value: 'inactive' },
                { label: t('users.statusLocked'), value: 'locked' },
              ]}
            />
            <Select
              value={roleFilter}
              onChange={setRoleFilter}
              style={{ width: 140 }}
              options={[
                { label: t('users.allRoles'), value: 'all' },
                ...roles.map(r => ({ label: r.name, value: r.id })),
              ]}
            />
          </div>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleOpenCreate}
          >
            {t('users.createUser')}
          </Button>
        </div>

        {/* Table */}
        {filteredUsers.length === 0 ? (
          <Empty
            image={<UserIcon className="h-10 w-10" style={{ color: isDark ? '#595959' : '#bfbfbf' }} />}
            description={
              <div>
                <Title level={5}>{t('users.emptyTitle')}</Title>
                <Text type="secondary">{t('users.emptyDesc')}</Text>
              </div>
            }
          >
            <Button type="primary" onClick={handleOpenCreate}>{t('users.createUser')}</Button>
          </Empty>
        ) : (
          <Table
            dataSource={filteredUsers.map(u => ({ ...u, key: u.id }))}
            columns={columns}
            pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => t('users.totalUsers').replace('{total}', String(total)) }}
            size="middle"
          />
        )}
      </Card>

      {/* Create/Edit Modal */}
      <ResizableModal
        title={editingUser ? t('users.editUser') : t('users.createUserTitle')}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        okText={t('users.saveBtn')}
        cancelText={t('users.cancelBtn')}
        width={600}
        destroyOnClose
        draggable
        resizable
      >
        <Form
          form={form}
          layout="vertical"
          className="mt-4"
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4">
            <Form.Item
              label={t('users.usernameLabel')}
              name="username"
              rules={[{ required: true, message: t('users.usernameRequired') }]}
            >
              <Input prefix={<UserOutlined />} placeholder={t('users.usernamePlaceholder')} />
            </Form.Item>
            <Form.Item
              label={t('users.emailLabel')}
              name="email"
              rules={[
                { required: true, message: t('users.emailRequired') },
                { type: 'email', message: t('users.emailInvalid') },
              ]}
            >
              <Input prefix={<MailOutlined />} placeholder={t('users.emailPlaceholder')} />
            </Form.Item>
            <Form.Item
              label={editingUser ? t('users.passwordEditLabel') : t('users.passwordLabel')}
              name="password"
              rules={editingUser ? [] : [{ required: true, message: t('users.passwordRequired') }]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder={editingUser ? t('users.passwordEditPlaceholder') : t('users.passwordPlaceholder')} />
            </Form.Item>
            <Form.Item label={t('users.phoneLabel')} name="phone">
              <Input prefix={<PhoneOutlined />} placeholder={t('users.phonePlaceholder')} />
            </Form.Item>
            <Form.Item label={t('users.departmentLabel')} name="department">
              <Input prefix={<BankOutlined />} placeholder={t('users.departmentPlaceholder')} />
            </Form.Item>
            <Form.Item
              label={t('users.statusLabel')}
              name="status"
              rules={[{ required: true }]}
            >
              <Select options={[
                { label: t('users.statusActive'), value: 'active' },
                { label: t('users.statusInactive'), value: 'inactive' },
                { label: t('users.statusLocked'), value: 'locked' },
              ]} />
            </Form.Item>
          </div>
          <Form.Item label={t('users.bioLabel')} name="bio">
            <TextArea rows={3} placeholder={t('users.bioPlaceholder')} />
          </Form.Item>
          <Form.Item label={t('users.roleLabel')} name="roleIds">
            <Select
              mode="multiple"
                            placeholder={t('users.rolePlaceholder')}
              options={roles.map(r => ({
                label: (
                  <span className="flex items-center gap-2">
                    {r.name}
                    <Text type="secondary" className="text-xs">- {r.description}</Text>
                    {r.isSystem && <Tag color="blue" style={{ fontSize: 9 }}>{t('users.systemTag')}</Tag>}
                  </span>
                ),
                value: r.id,
              }))}
            />
          </Form.Item>
        </Form>
      </ResizableModal>
    </div>
  );
};
