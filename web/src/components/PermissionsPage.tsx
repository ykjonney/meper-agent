import React, { useState } from 'react';
import { useAppState } from '../AppContext';
import { Permission } from '../types';
import { useTheme } from '../ThemeContext';
import { useTranslation } from '../LocaleContext';
import { Key } from 'lucide-react';
import {
  Table, Tag, Button, Input, Select, Switch, Space,
  Collapse, Progress, Empty, Typography, Tooltip, Card
} from 'antd';
import { SearchOutlined, KeyOutlined } from '@ant-design/icons';

const { Title, Text } = Typography;

export const PermissionsPage: React.FC = () => {
  const { permissions, updatePermission } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();

  const [searchQuery, setSearchQuery] = useState('');
  const [moduleFilter, setModuleFilter] = useState<string>('all');

  // Group by module
  const permissionsByModule = permissions.reduce<Record<string, Permission[]>>((acc, p) => {
    if (!acc[p.module]) acc[p.module] = [];
    acc[p.module].push(p);
    return acc;
  }, {} as Record<string, Permission[]>);

  const modules = Object.keys(permissionsByModule);

  const filtered = permissions.filter(p => {
    const matchSearch = p.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        p.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        p.module.toLowerCase().includes(searchQuery.toLowerCase());
    const matchModule = moduleFilter === 'all' || p.module === moduleFilter;
    return matchSearch && matchModule;
  });

  const toggleEnabled = (perm: Permission) => {
    updatePermission(perm.id, { enabled: !perm.enabled });
  };

  const totalEnabled = permissions.filter(p => p.enabled).length;

  // Build table data source grouped by module
  const tableDataSource = filtered.map(p => ({
    ...p,
    key: p.id,
  }));

  const columns = [
    {
      title: t('permissions.columnModule'),
      dataIndex: 'module',
      key: 'module',
      width: 120,
      filters: modules.map(m => ({ text: m, value: m })),
      onFilter: (value: unknown, record: Permission) => record.module === value,
      render: (module: string) => (
        <Tag style={{ fontSize: 11 }}>{module}</Tag>
      ),
    },
    {
      title: t('permissions.columnAction'),
      dataIndex: 'action',
      key: 'action',
      width: 100,
      render: (action: string) => (
        <Text code className="text-xs">{action}</Text>
      ),
    },
    {
      title: t('permissions.columnLabel'),
      dataIndex: 'label',
      key: 'label',
      render: (label: string) => <Text className="text-sm">{label}</Text>,
    },
    {
      title: t('permissions.columnDesc'),
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (desc: string) => <Text type="secondary" className="text-xs">{desc}</Text>,
    },
    {
      title: t('permissions.columnStatus'),
      dataIndex: 'enabled',
      key: 'enabled',
      width: 100,
      render: (enabled: boolean, record: Permission) => (
        <Switch
          checked={enabled}
          onChange={() => toggleEnabled(record)}
          checkedChildren={t('permissions.switchOn')}
          unCheckedChildren={t('permissions.switchOff')}
        />
      ),
    },
  ];

  // Module summary cards for the top
  const moduleSummaries = modules.map(module => {
    const perms = permissionsByModule[module];
    const enabledCount = perms.filter(p => p.enabled).length;
    return { module, total: perms.length, enabled: enabledCount, percent: Math.round((enabledCount / perms.length) * 100) };
  });

  return (
    <div className="px-4 py-6">
      <Card size="small">
        {/* Module summary bar */}
        <div className="flex flex-wrap gap-3 mb-4">
          {moduleSummaries.map(ms => (
            <div
              key={ms.module}
              className="flex items-center gap-2 px-3 py-2 rounded-lg border"
              style={{
                background: isDark ? '#141414' : '#fafafa',
                borderColor: isDark ? '#303030' : '#f0f0f0',
              }}
            >
              <Text className="text-xs font-medium">{ms.module}</Text>
              <Progress
                type="circle"
                size={28}
                percent={ms.percent}
                format={() => ''}
                strokeColor="#1677ff"
              />
              <Text type="secondary" className="text-xs">{ms.enabled}/{ms.total}</Text>
            </div>
          ))}
        </div>

        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <Input
            prefix={<SearchOutlined />}
            placeholder={t('permissions.searchPlaceholder')}
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            style={{ width: 200 }}
            allowClear
          />
          <Select
            value={moduleFilter}
            onChange={setModuleFilter}
            style={{ width: 140 }}
            options={[
              { label: t('permissions.allModules'), value: 'all' },
              ...modules.map(m => ({ label: m, value: m })),
            ]}
          />
        </div>

        {/* Table */}
        {filtered.length === 0 ? (
          <Empty
            image={<Key className="h-10 w-10" style={{ color: isDark ? '#595959' : '#bfbfbf' }} />}
            description={
              <div>
                <Title level={5}>{t('permissions.emptyTitle')}</Title>
                <Text type="secondary">{t('permissions.emptyDesc')}</Text>
              </div>
            }
          />
        ) : (
          <Table
            dataSource={tableDataSource}
            columns={columns}
            pagination={{ pageSize: 15, showSizeChanger: true, showTotal: (total) => t('permissions.totalPermissions').replace('{total}', String(total)) }}
            size="middle"
            rowClassName={(record) =>
              record.enabled ? '' : 'opacity-60'
            }
          />
        )}
      </Card>
    </div>
  );
};
