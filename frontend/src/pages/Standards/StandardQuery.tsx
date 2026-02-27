import { useState } from 'react';
import {
  Card,
  Form,
  Select,
  InputNumber,
  Button,
  Space,
  Alert,
  List,
  Tag,
  Typography,
  message,
} from 'antd';
import { SearchOutlined, CheckCircleOutlined } from '@ant-design/icons';
import { recommendParams, checkConstraints } from '../../services/api.ts';
import type { ParamRecommendation, ConstraintViolation } from '../../types/standard.ts';

const { Title, Text } = Typography;

const PART_TYPE_OPTIONS = [
  { label: '回转体', value: 'rotational' },
  { label: '阶梯回转体', value: 'rotational_stepped' },
  { label: '齿轮', value: 'gear' },
];

const PARAM_SUGGESTIONS: Record<string, string[]> = {
  rotational: ['outer_diameter', 'thickness', 'pcd', 'hole_count', 'hole_diameter', 'bore_diameter', 'bolt_size', 'wall_thickness'],
  rotational_stepped: ['shaft_diameter', 'key_width', 'shaft_groove_depth'],
  gear: ['module', 'teeth'],
};

export default function StandardQuery() {
  const [partType, setPartType] = useState('rotational');
  const [params, setParams] = useState<Record<string, number>>({});
  const [recommendations, setRecommendations] = useState<ParamRecommendation[]>([]);
  const [violations, setViolations] = useState<ConstraintViolation[]>([]);
  const [checkValid, setCheckValid] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);

  const availableParams = PARAM_SUGGESTIONS[partType] ?? [];

  const handleRecommend = async () => {
    setLoading(true);
    try {
      const res = await recommendParams({ part_type: partType, known_params: params });
      setRecommendations(res.recommendations);
    } catch {
      message.error('参数推荐请求失败');
    } finally {
      setLoading(false);
    }
  };

  const handleCheck = async () => {
    setLoading(true);
    try {
      const res = await checkConstraints({ part_type: partType, params });
      setViolations(res.violations);
      setCheckValid(res.valid);
    } catch {
      message.error('约束检查请求失败');
    } finally {
      setLoading(false);
    }
  };

  const handleParamChange = (name: string, value: number | null) => {
    setParams((prev) => {
      if (value === null) {
        const next = { ...prev };
        delete next[name];
        return next;
      }
      return { ...prev, [name]: value };
    });
  };

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Title level={5}>参数查询</Title>
        <Form layout="inline" style={{ flexWrap: 'wrap', gap: 8 }}>
          <Form.Item label="零件类型">
            <Select
              value={partType}
              onChange={(v) => {
                setPartType(v);
                setParams({});
                setRecommendations([]);
                setViolations([]);
                setCheckValid(null);
              }}
              options={PART_TYPE_OPTIONS}
              style={{ width: 160 }}
            />
          </Form.Item>
          {availableParams.map((name) => (
            <Form.Item label={name} key={name}>
              <InputNumber
                value={params[name] ?? null}
                onChange={(v) => handleParamChange(name, v)}
                style={{ width: 120 }}
                placeholder="mm"
              />
            </Form.Item>
          ))}
        </Form>

        <Space style={{ marginTop: 16 }}>
          <Button
            type="primary"
            icon={<SearchOutlined />}
            onClick={handleRecommend}
            loading={loading}
          >
            参数推荐
          </Button>
          <Button
            icon={<CheckCircleOutlined />}
            onClick={handleCheck}
            loading={loading}
          >
            约束检查
          </Button>
        </Space>
      </Card>

      {recommendations.length > 0 && (
        <Card title="推荐参数">
          <List
            size="small"
            dataSource={recommendations}
            renderItem={(rec) => (
              <List.Item>
                <Space>
                  <Tag color="blue">{rec.param_name}</Tag>
                  <Text strong>
                    {rec.value} {rec.unit}
                  </Text>
                  <Text type="secondary">{rec.reason}</Text>
                  {rec.source && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      [{rec.source}]
                    </Text>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </Card>
      )}

      {checkValid !== null && (
        <Card title="约束检查结果">
          {checkValid ? (
            <Alert type="success" message="所有约束检查通过" showIcon />
          ) : (
            <Space orientation="vertical" size={8} style={{ width: '100%' }}>
              {violations.map((v, i) => (
                <Alert
                  key={i}
                  type={v.severity === 'error' ? 'error' : 'warning'}
                  message={v.message}
                  description={
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      约束: {v.constraint}
                    </Text>
                  }
                  showIcon
                />
              ))}
            </Space>
          )}
        </Card>
      )}
    </Space>
  );
}
