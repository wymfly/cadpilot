import { useState, useEffect } from 'react';
import {
  Card,
  Table,
  Select,
  Empty,
  Spin,
  Typography,
  Tag,
  message,
} from 'antd';
import { getStandardCategories, getStandardEntries } from '../../services/api.ts';
import type { StandardEntry } from '../../types/standard.ts';

const { Title, Text } = Typography;

const CATEGORY_LABELS: Record<string, string> = {
  bolt: '螺栓标准',
  flange: '法兰标准',
  tolerance: '配合公差',
  keyway: '键/键槽标准',
  gear: '齿轮模数',
};

const CATEGORY_COLORS: Record<string, string> = {
  bolt: 'blue',
  flange: 'green',
  tolerance: 'orange',
  keyway: 'purple',
  gear: 'magenta',
};

export default function StandardBrowser() {
  const [categories, setCategories] = useState<string[]>([]);
  const [selected, setSelected] = useState('');
  const [entries, setEntries] = useState<StandardEntry[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getStandardCategories()
      .then((cats) => {
        setCategories(cats);
        if (cats.length > 0) setSelected(cats[0]);
      })
      .catch(() => message.error('加载标准分类失败'));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    getStandardEntries(selected)
      .then(setEntries)
      .catch(() => message.error('加载标准数据失败'))
      .finally(() => setLoading(false));
  }, [selected]);

  const paramColumns = entries.length > 0
    ? Object.keys(entries[0].params).map((key) => ({
        title: key,
        dataIndex: ['params', key],
        key,
        render: (val: number | string) =>
          typeof val === 'number' ? String(val) : val,
      }))
    : [];

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => <Text strong>{name}</Text>,
    },
    ...paramColumns,
  ];

  return (
    <Card>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <Title level={5} style={{ margin: 0 }}>标准类别</Title>
        <Select
          value={selected}
          onChange={setSelected}
          style={{ width: 200 }}
          options={categories.map((c) => ({
            label: CATEGORY_LABELS[c] ?? c,
            value: c,
          }))}
        />
        {selected && (
          <Tag color={CATEGORY_COLORS[selected] ?? 'default'}>
            {entries.length} 条记录
          </Tag>
        )}
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin size="large" />
        </div>
      ) : entries.length === 0 ? (
        <Empty description="暂无数据" />
      ) : (
        <Table
          columns={columns}
          dataSource={entries}
          rowKey="name"
          pagination={false}
          size="small"
          scroll={{ x: 'max-content' }}
        />
      )}
    </Card>
  );
}
