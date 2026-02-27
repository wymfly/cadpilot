import { useState, useEffect, useMemo } from 'react';
import {
  Card,
  Tag,
  Input,
  Select,
  Row,
  Col,
  Empty,
  Button,
  Space,
  Spin,
  Typography,
  message,
} from 'antd';
import { PlusOutlined, SearchOutlined } from '@ant-design/icons';
import { getTemplates } from '../../services/api.ts';
import type { ParametricTemplate } from '../../types/template.ts';

const { Title, Paragraph, Text } = Typography;

const PART_TYPES = [
  { label: '全部', value: '' },
  { label: '回转体', value: 'rotational' },
  { label: '阶梯回转体', value: 'rotational_stepped' },
  { label: '板件', value: 'plate' },
  { label: '支架', value: 'bracket' },
  { label: '壳体', value: 'housing' },
  { label: '齿轮', value: 'gear' },
  { label: '通用', value: 'general' },
];

const PART_TYPE_COLORS: Record<string, string> = {
  rotational: 'blue',
  rotational_stepped: 'cyan',
  plate: 'green',
  bracket: 'orange',
  housing: 'purple',
  gear: 'magenta',
  general: 'default',
};

interface TemplateListProps {
  onSelect: (name: string) => void;
  onCreate: () => void;
}

export default function TemplateList({ onSelect, onCreate }: TemplateListProps) {
  const [templates, setTemplates] = useState<ParametricTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [partType, setPartType] = useState('');

  useEffect(() => {
    setLoading(true);
    getTemplates(partType || undefined)
      .then(setTemplates)
      .catch(() => {
        message.error('加载模板列表失败');
      })
      .finally(() => setLoading(false));
  }, [partType]);

  const filtered = useMemo(() => {
    if (!search) return templates;
    const keyword = search.toLowerCase();
    return templates.filter(
      (t) =>
        t.name.toLowerCase().includes(keyword) ||
        t.display_name.toLowerCase().includes(keyword) ||
        t.description.toLowerCase().includes(keyword),
    );
  }, [templates, search]);

  const partTypeLabel = (value: string) =>
    PART_TYPES.find((p) => p.value === value)?.label ?? value;

  return (
    <div>
      <Space
        style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}
      >
        <Title level={3} style={{ margin: 0 }}>
          参数化模板
        </Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
          新建模板
        </Button>
      </Space>

      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          placeholder="搜索模板名称或描述"
          prefix={<SearchOutlined />}
          allowClear
          style={{ width: 260 }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <Select
          value={partType}
          onChange={setPartType}
          options={PART_TYPES}
          style={{ width: 160 }}
          placeholder="零件类型"
        />
      </Space>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin size="large" />
        </div>
      ) : filtered.length === 0 ? (
        <Empty description="暂无模板" style={{ marginTop: 48 }} />
      ) : (
        <Row gutter={[16, 16]}>
          {filtered.map((tpl) => (
            <Col xs={24} sm={12} lg={8} key={tpl.name}>
              <Card
                hoverable
                onClick={() => onSelect(tpl.name)}
                styles={{ body: { padding: 20 } }}
              >
                <Space orientation="vertical" size={8} style={{ width: '100%' }}>
                  <Space>
                    <Text strong style={{ fontSize: 16 }}>
                      {tpl.display_name}
                    </Text>
                    <Tag color={PART_TYPE_COLORS[tpl.part_type] ?? 'default'}>
                      {partTypeLabel(tpl.part_type)}
                    </Tag>
                  </Space>
                  <Paragraph
                    type="secondary"
                    ellipsis={{ rows: 2 }}
                    style={{ marginBottom: 0 }}
                  >
                    {tpl.description}
                  </Paragraph>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {tpl.params.length} 个参数 · {tpl.constraints.length} 个约束
                  </Text>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </div>
  );
}
