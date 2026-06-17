import React, { useState } from 'react';
import { useAppState } from '../AppContext';
import { Role, Permission } from '../types';
import { useTheme } from '../ThemeContext';
import { useTranslation } from '../LocaleContext';
import {
  Shield, Users, CheckSquare
} from 'lucide-react';
import {
  Table, Tag, Button, Input, Select, Space, Modal, Form,
  Checkbox, Tooltip, Empty, Typography, Popconfirm, message, Collapse, Card
} from 'antd';
import {
  PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined,
  SafetyOutlined, UserOutlined, CheckCircleOutlined
} from '@ant-design/icons';
import { ResizableModal } from './ResizableModal';

const { TextArea } = Input;
const { Title, Text } = Typography;

export const RolesPage: React.FC = () => {
  const { roles, permissions, users, addRole, updateRole, deleteRole } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();

  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [expandedRoleId, setExpandedRoleId] = useState<string | null>(null);
  const [form] = Form.useForm();

  // Group permissions by module
  const permissionsByModule = permissions.reduce((acc: Record<string, Permission[]>, p) => {
    if (!acc[p.module]) acc[p.module] = [];
    acc[p.module].push(p);
    return acc;
  }, {} as Record<string, Permission[]>);

  const filteredRoles = roles.filter(r => {
    const matchSearch = r.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        r.code.toLowerCase().includes(searchQuery.toLowerCase());
    const matchType = typeFilter === 'all' ||
                      (typeFilter === 'system' && r.isSystem) ||
                      (typeFilter === 'custom' && !r.isSystem);
    return matchSearch && matchType;
  });

  const getUserCountByRole = (roleId: string) =>
    users.filter(u => u.roleIds.includes(roleId)).length;

  const handleOpenCreate = () => {
    setEditingRole(null);
    form.resetFields();
    form.setFieldsValue({ permissionIds: [] });
    setModalOpen(true);
  };

  const handleOpenEdit = (role: Role) => {
    setEditingRole(role);
    form.setFieldsValue({
      name: role.name,
      code: role.code,
      description: role.description,
      permissionIds: [...role.permissionIds],
    });
    setModalOpen(true);
  };

  const handleSubmit = () => {
    form.validateFields().then(values => {
      if (editingRole) {
        updateRole({
          ...editingRole,
          name: values.name.trim(),
          code: values.code.trim(),
          description: values.description.trim(),
          permissionIds: values.permissionIds,
        });
        message.success(t('roles.roleUpdated'));
      } else {
        addRole({
          name: values.name.trim(),
          code: values.code.trim(),
          description: values.description.trim(),
          permissionIds: values.permissionIds,
          isSystem: false,
        });
        message.success(t('roles.roleCreated'));
      }
      setModalOpen(false);
    });
  };

  const handleDelete = (id: string) => {
    deleteRole(id);
    message.success(t('roles.roleDeleted'));
  };

  const columns = [
    {
      title: t('roles.columnRole'),
      key: 'role',
      render: (_: unknown, record: Role) => (
        <div className="flex items-center gap-2">
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
            style={{ background: isDark ? '#220e4a' : '#f9f0ff' }}
          >
            <SafetyOutlined style={{ color: '#722ed1' }} />
          </div>
          <div>
            <div className="font-semibold text-sm flex items-center gap-2">
              {record.name}
              {record.isSystem && <Tag color="blue" style={{ fontSize: 9 }}>{t('roles.systemTag')}</Tag>}
            </div>
            <Text type="secondary" className="text-xs font-mono">{record.code}</Text>
          </div>
        </div>
      ),
    },
    {
      title: t('roles.columnDesc'),
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (text: string) => <Text className="text-xs">{text}</Text>,
    },
    {
      title: t('roles.columnUserCount'),
      key: 'userCount',
      width: 90,
      sorter: (a: Role, b: Role) => getUserCountByRole(a.id) - getUserCountByRole(b.id),
      render: (_: unknown, record: Role) => (
        <span className="flex items-center gap-1 text-xs">
          <UserOutlined />
          {getUserCountByRole(record.id)}
        </span>
      ),
    },
    {
      title: t('roles.columnPermCount'),
      dataIndex: 'permissionIds',
      key: 'permCount',
      width: 90,
      sorter: (a: Role, b: Role) => a.permissionIds.length - b.permissionIds.length,
      render: (permIds: string[]) => (
        <span className="flex items-center gap-1 text-xs">
          <CheckCircleOutlined />
          {permIds.length}
        </span>
      ),
    },
    {
      title: t('roles.columnActions'),
      key: 'actions',
      width: 160,
      render: (_: unknown, record: Role) => (
        <Space size={4}>
          <Tooltip title={t('roles.editTooltip')}>
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleOpenEdit(record)}
            />
          </Tooltip>
          {!record.isSystem && (
            <Popconfirm
              title={t('roles.confirmDelete').replace('{name}', record.name)}
              onConfirm={() => handleDelete(record.id)}
              okText={t('roles.okText')}
              cancelText={t('roles.cancelText')}
            >
              <Tooltip title={t('roles.deleteTooltip')}>
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Tooltip>
            </Popconfirm>
          )}
          <Tooltip title={expandedRoleId === record.id ? t('roles.collapsePerms') : t('roles.expandPerms')}>
            <Button
              size="small"
              type={expandedRoleId === record.id ? 'primary' : 'default'}
              ghost={expandedRoleId === record.id}
              icon={<SafetyOutlined />}
              onClick={() => setExpandedRoleId(expandedRoleId === record.id ? null : record.id)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  // Build expanded permission detail
  const expandedRowRender = (record: Role) => {
    const enabledPerms = (Object.entries(permissionsByModule) as [string, Permission[]][]).map(([module, perms]) => {
      const enabled = perms.filter(p => record.permissionIds.includes(p.id));
      if (enabled.length === 0) return null;
      return (
        <div key={module} className="mb-3">
          <Text type="secondary" className="text-xs font-medium block mb-1">{module}</Text>
          <Space size={[4, 4]} wrap>
            {enabled.map(p => (
              <Tag key={p.id} style={{ fontSize: 11 }}>{p.label}</Tag>
            ))}
          </Space>
        </div>
      );
    }).filter(Boolean);

    return <div className="py-2 px-2">{enabledPerms}</div>;
  };

  return (
    <div className="px-4 py-6">
      <Card size="small">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="flex flex-wrap items-center gap-3">
            <Input
              prefix={<SearchOutlined />}
              placeholder={t('roles.searchPlaceholder')}
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={{ width: 200 }}
              allowClear
            />
            <Select
              value={typeFilter}
              onChange={setTypeFilter}
              style={{ width: 130 }}
              options={[
                { label: t('roles.allTypes'), value: 'all' },
                { label: t('roles.systemRole'), value: 'system' },
                { label: t('roles.customRole'), value: 'custom' },
              ]}
            />
          </div>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleOpenCreate}
          >
            {t('roles.createRole')}
          </Button>
        </div>

        {/* Table */}
        {filteredRoles.length === 0 ? (
          <Empty
            image={<Shield className="h-10 w-10" style={{ color: isDark ? '#595959' : '#bfbfbf' }} />}
            description={
              <div>
                <Title level={5}>{t('roles.emptyTitle')}</Title>
                <Text type="secondary">{t('roles.emptyDesc')}</Text>
              </div>
            }
          >
            <Button type="primary" onClick={handleOpenCreate}>{t('roles.createRole')}</Button>
          </Empty>
        ) : (
          <Table
            dataSource={filteredRoles.map(r => ({ ...r, key: r.id }))}
            columns={columns}
            pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => t('roles.totalRoles').replace('{total}', String(total)) }}
            size="middle"
            expandable={{
              expandedRowKeys: expandedRoleId ? [expandedRoleId] : [],
              expandedRowRender,
              onExpand: (expanded, record) => {
                setExpandedRoleId(expanded ? record.id : null);
              },
            }}
          />
        )}
      </Card>

      {/* Create/Edit Modal */}
      <ResizableModal
        title={editingRole ? t('roles.editRole') : t('roles.createRoleTitle')}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        okText={t('roles.saveBtn')}
        cancelText={t('roles.cancelBtn')}
        width={640}
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
              label={t('roles.nameLabel')}
              name="name"
              rules={[{ required: true, message: t('roles.nameRequired') }]}
            >
              <Input placeholder={t('roles.namePlaceholder')} />
            </Form.Item>
            <Form.Item
              label={t('roles.codeLabel')}
              name="code"
              rules={[{ required: true, message: t('roles.codeRequired') }]}
            >
              <Input placeholder={t('roles.codePlaceholder')} className="font-mono" />
            </Form.Item>
          </div>
          <Form.Item label={t('roles.descLabel')} name="description">
            <TextArea rows={2} placeholder={t('roles.descPlaceholder')} />
          </Form.Item>

          {/* Permission assignment with module grouping */}
          <Form.Item label={t('roles.permissionLabel')} name="permissionIds">
            <PermissionSelector permissions={permissions} />
          </Form.Item>
        </Form>
      </ResizableModal>
    </div>
  );
};

/** Internal component: Permission selector grouped by module with Checkbox.Group */
const PermissionSelector: React.FC<{ permissions: Permission[] }> = ({ permissions }) => {
  const { t } = useTranslation();

  const permissionsByModule = permissions.reduce((acc: Record<string, Permission[]>, p) => {
    if (!acc[p.module]) acc[p.module] = [];
    acc[p.module].push(p);
    return acc;
  }, {} as Record<string, Permission[]>);

  return (
    <div className="border rounded-lg p-3 max-h-[300px] overflow-y-auto">
      <Collapse
        ghost
        size="small"
        items={(Object.entries(permissionsByModule) as [string, Permission[]][]).map(([module, perms]) => ({
          key: module,
          label: (
            <span className="text-sm font-medium flex items-center gap-2">
              <CheckSquare className="h-3.5 w-3.5 text-blue-500" />
              {module}
              <Text type="secondary" className="text-xs">({perms.length} {t('roles.permItemCount').replace('{count}', String(perms.length))})</Text>
            </span>
          ),
          children: (
            <Checkbox.Group
              style={{ width: '100%' }}
              options={perms.map(p => ({
                label: p.label,
                value: p.id,
              }))}
              className="flex flex-wrap gap-2"
            />
          ),
        }))}
      />
    </div>
  );
};
