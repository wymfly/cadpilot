import { useState, useEffect } from 'react';
import {
  Typography,
  Descriptions,
  Table,
  Card,
  Button,
  Space,
  Spin,
  Tag,
  InputNumber,
  message,
  Popconfirm,
  Alert,
} from 'antd';
import {
  ArrowLeftOutlined,
  EditOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  getTemplate,
  deleteTemplate,
  validateTemplateParams,
} from '../../services/api.ts';
import type {
  ParametricTemplate,
  ParamDefinition,
  ValidateResponse,
} from '../../types/template.ts';

const { Title, Text } = Typography;

const PART_TYPE_LABELS: Record<string, string> = {
  rotational: '回转体',
  rotational_stepped: '阶梯回转体',
  plate: '板件',
  bracket: '支架',
  housing: '壳体',
  gear: '齿轮',
  general: '通用',
};

const paramColumns: ColumnsType<ParamDefinition> = [
  {
    title: '参数名',
    dataIndex: 'name',
    key: 'name',
    width: 140,
    render: (val: string) => <Text code>{val}</Text>,
  },
  {
    title: '显示名',
    dataIndex: 'display_name',
    key: 'display_name',
    width: 120,
  },
  {
    title: '单位',
    dataIndex: 'unit',
    key: 'unit',
    width: 60,
    render: (val?: string) => val ?? '-',
  },
  {
    title: '类型',
    dataIndex: 'param_type',
    key: 'param_type',
    width: 80,
    render: (val: string) => <Tag>{val}</Tag>,
  },
  {
    title: '范围',
    key: 'range',
    width: 120,
    render: (_: unknown, record: ParamDefinition) => {
      if (record.range_min != null && record.range_max != null) {
        return `${record.range_min} ~ ${record.range_max}`;
      }
      if (record.range_min != null) return `>= ${record.range_min}`;
      if (record.range_max != null) return `<= ${record.range_max}`;
      return '-';
    },
  },
  {
    title: '默认值',
    dataIndex: 'default',
    key: 'default',
    width: 80,
    render: (val?: number | string | boolean) =>
      val != null ? String(val) : '-',
  },
  {
    title: '依赖',
    dataIndex: 'depends_on',
    key: 'depends_on',
    width: 100,
    render: (val?: string) => (val ? <Text code>{val}</Text> : '-'),
  },
];

interface TemplateDetailProps {
  name: string;
  onBack: () => void;
  onEdit: () => void;
}

export default function TemplateDetail({
  name,
  onBack,
  onEdit,
}: TemplateDetailProps) {
  const [template, setTemplate] = useState<ParametricTemplate | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);

  // Validation state
  const [paramValues, setParamValues] = useState<Record<string, number>>({});
  const [validating, setValidating] = useState(false);
  const [validateResult, setValidateResult] = useState<ValidateResponse | null>(
    null,
  );

  useEffect(() => {
    setLoading(true);
    getTemplate(name)
      .then((tpl) => {
        setTemplate(tpl);
        // Initialize param values with defaults
        const defaults: Record<string, number> = {};
        for (const p of tpl.params) {
          if (typeof p.default === 'number') {
            defaults[p.name] = p.default;
          }
        }
        setParamValues(defaults);
      })
      .catch(() => {
        message.error('加载模板详情失败');
      })
      .finally(() => setLoading(false));
  }, [name]);

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteTemplate(name);
      message.success('模板已删除');
      onBack();
    } catch {
      message.error('删除失败');
    } finally {
      setDeleting(false);
    }
  };

  const handleValidate = async () => {
    setValidating(true);
    setValidateResult(null);
    try {
      const result = await validateTemplateParams(name, paramValues);
      setValidateResult(result);
    } catch {
      message.error('验证请求失败');
    } finally {
      setValidating(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!template) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Text type="secondary">模板不存在或加载失败</Text>
        <br />
        <Button style={{ marginTop: 16 }} onClick={onBack}>
          返回列表
        </Button>
      </div>
    );
  }

  return (
    <div>
      <Space
        style={{
          width: '100%',
          justifyContent: 'space-between',
          marginBottom: 16,
        }}
      >
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={onBack}>
            返回列表
          </Button>
          <Title level={3} style={{ margin: 0 }}>
            {template.display_name}
          </Title>
        </Space>
        <Space>
          <Button icon={<EditOutlined />} onClick={onEdit}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除此模板？"
            description="删除后无法恢复"
            onConfirm={handleDelete}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button danger icon={<DeleteOutlined />} loading={deleting}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      </Space>

      <Descriptions bordered size="small" column={{ xs: 2, sm: 3 }}>
        <Descriptions.Item label="模板名称">
          <Text code>{template.name}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="零件类型">
          <Tag>{PART_TYPE_LABELS[template.part_type] ?? template.part_type}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="描述">
          {template.description}
        </Descriptions.Item>
        {template.constraints.length > 0 && (
          <Descriptions.Item label="约束条件" span={3}>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {template.constraints.map((c, i) => (
                <li key={i}>
                  <Text code>{c}</Text>
                </li>
              ))}
            </ul>
          </Descriptions.Item>
        )}
      </Descriptions>

      <Card
        size="small"
        title="参数定义"
        style={{ marginTop: 16 }}
      >
        <Table<ParamDefinition>
          columns={paramColumns}
          dataSource={template.params}
          rowKey="name"
          pagination={false}
          size="small"
        />
      </Card>

      <Card
        size="small"
        title="代码模板"
        style={{ marginTop: 16 }}
      >
        <pre
          style={{
            background: '#f5f5f5',
            padding: 16,
            borderRadius: 6,
            overflow: 'auto',
            maxHeight: 400,
            fontSize: 13,
            lineHeight: 1.6,
            margin: 0,
          }}
        >
          <code>{template.code_template}</code>
        </pre>
      </Card>

      <Card
        size="small"
        title="在线验证"
        style={{ marginTop: 16 }}
      >
        <Space wrap style={{ marginBottom: 12 }}>
          {template.params
            .filter((p) => p.param_type === 'float' || p.param_type === 'int')
            .map((p) => (
              <Space key={p.name} size={4}>
                <Text style={{ fontSize: 13 }}>
                  {p.display_name}
                  {p.unit ? ` (${p.unit})` : ''}:
                </Text>
                <InputNumber
                  size="small"
                  value={paramValues[p.name]}
                  min={p.range_min}
                  max={p.range_max}
                  step={p.param_type === 'int' ? 1 : 0.1}
                  onChange={(val) =>
                    setParamValues((prev) => ({
                      ...prev,
                      [p.name]: val ?? 0,
                    }))
                  }
                />
              </Space>
            ))}
        </Space>
        <div>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={handleValidate}
            loading={validating}
          >
            验证
          </Button>
        </div>
        {validateResult && (
          <div style={{ marginTop: 12 }}>
            {validateResult.valid ? (
              <Alert
                type="success"
                showIcon
                icon={<CheckCircleOutlined />}
                message="验证通过"
                description="所有参数在有效范围内，约束条件满足。"
              />
            ) : (
              <Alert
                type="error"
                showIcon
                icon={<CloseCircleOutlined />}
                message="验证失败"
                description={
                  <ul style={{ margin: 0, paddingLeft: 16 }}>
                    {validateResult.errors.map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                }
              />
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
