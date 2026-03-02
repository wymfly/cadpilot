import { useState, useMemo } from 'react';
import {
  Form,
  InputNumber,
  Select,
  Checkbox,
  Button,
  Tag,
  Collapse,
  Alert,
  Space,
  Typography,
  Divider,
} from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';
import type { DrawingSpec, DrawingSpecFeature } from '../../types/generate.ts';

const { Text, Title } = Typography;

const PART_TYPE_OPTIONS = [
  { value: 'rotational', label: '回转体' },
  { value: 'rotational_stepped', label: '阶梯回转体' },
  { value: 'plate', label: '板件' },
  { value: 'bracket', label: '支架' },
  { value: 'housing', label: '壳体' },
  { value: 'gear', label: '齿轮' },
  { value: 'general', label: '通用' },
];

const BASE_BODY_METHOD_OPTIONS = [
  { value: 'revolve', label: '回转 (Revolve)' },
  { value: 'extrude', label: '拉伸 (Extrude)' },
  { value: 'loft', label: '放样 (Loft)' },
  { value: 'sweep', label: '扫掠 (Sweep)' },
  { value: 'shell', label: '抽壳 (Shell)' },
];

export interface DrawingSpecFormProps {
  drawingSpec: DrawingSpec;
  onConfirm: (spec: DrawingSpec, disclaimerAccepted: boolean) => void;
  onCancel: () => void;
}

export default function DrawingSpecForm({
  drawingSpec,
  onConfirm,
  onCancel,
}: DrawingSpecFormProps) {
  const dt = useDesignTokens();
  const [form] = Form.useForm();
  const [disclaimerAccepted, setDisclaimerAccepted] = useState(false);
  const [partType, setPartType] = useState(drawingSpec.part_type);
  const [baseBodyMethod, setBaseBodyMethod] = useState(drawingSpec.base_body.method);
  const [features, setFeatures] = useState<DrawingSpecFeature[]>(drawingSpec.features);

  const confidence = drawingSpec.confidence ?? 0;

  const confidenceTag = useMemo(() => {
    if (confidence >= 0.8) {
      return <Tag color="green">置信度 {(confidence * 100).toFixed(0)}%</Tag>;
    }
    if (confidence >= 0.5) {
      return <Tag color="orange">置信度 {(confidence * 100).toFixed(0)}%</Tag>;
    }
    return <Tag color="red">置信度 {(confidence * 100).toFixed(0)}%</Tag>;
  }, [confidence]);

  const handleConfirm = () => {
    const dims = form.getFieldsValue() as Record<string, number>;
    const confirmedSpec: DrawingSpec = {
      part_type: partType,
      description: drawingSpec.description ?? '',
      overall_dimensions: dims,
      base_body: { ...drawingSpec.base_body, method: baseBodyMethod },
      features,
      notes: drawingSpec.notes,
      confidence: drawingSpec.confidence,
    };
    onConfirm(confirmedSpec, disclaimerAccepted);
  };

  const handleRemoveFeature = (index: number) => {
    setFeatures((prev) => prev.filter((_, i) => i !== index));
  };

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Title level={5} style={{ margin: 0 }}>图纸分析结果</Title>
        {confidenceTag}
      </Space>

      {/* 零件类型 */}
      <div style={{ marginBottom: 12 }}>
        <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>
          零件类型
        </Text>
        <Select
          value={partType}
          onChange={setPartType}
          options={PART_TYPE_OPTIONS}
          style={{ width: '100%' }}
          size="small"
        />
      </div>

      {/* 总体尺寸 */}
      <div style={{ marginBottom: 12 }}>
        <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>
          总体尺寸
        </Text>
        <Form
          form={form}
          layout="vertical"
          size="small"
          initialValues={drawingSpec.overall_dimensions}
        >
          {Object.entries(drawingSpec.overall_dimensions).map(([key]) => (
            <Form.Item
              key={key}
              name={key}
              label={key}
              style={{ marginBottom: 8 }}
            >
              <InputNumber
                precision={2}
                min={0}
                addonAfter="mm"
                style={{ width: '100%' }}
              />
            </Form.Item>
          ))}
        </Form>
      </div>

      {/* 基体 */}
      <div style={{ marginBottom: 12 }}>
        <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>
          建模方法
        </Text>
        <Select
          value={baseBodyMethod}
          onChange={setBaseBodyMethod}
          options={BASE_BODY_METHOD_OPTIONS}
          style={{ width: '100%' }}
          size="small"
        />
      </div>

      {/* 特征列表 */}
      {features.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>
            特征 ({features.length})
          </Text>
          <Collapse
            size="small"
            items={features.map((feat, i) => ({
              key: i,
              label: (
                <Space>
                  <Text style={{ fontSize: 12 }}>{feat.type}</Text>
                  <Tag style={{ fontSize: 11 }}>
                    {Object.keys(feat).filter((k) => k !== 'type').length} 参数
                  </Tag>
                </Space>
              ),
              extra: (
                <Button
                  type="text"
                  danger
                  size="small"
                  icon={<DeleteOutlined />}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleRemoveFeature(i);
                  }}
                />
              ),
              children: (
                <pre style={{ fontSize: 11, margin: 0, whiteSpace: 'pre-wrap', fontFamily: dt.typography.fontMono }}>
                  {JSON.stringify(feat, null, 2)}
                </pre>
              ),
            }))}
          />
        </div>
      )}

      <Divider style={{ margin: '12px 0' }} />

      {/* 免责声明 */}
      <div className="caution-stripe">
        <Alert
          type="warning"
          message="AI 识别结果仅供参考，请核对关键参数"
          style={{ marginBottom: 8, fontSize: 12 }}
          showIcon
        />
        <Checkbox
          checked={disclaimerAccepted}
          onChange={(e) => setDisclaimerAccepted(e.target.checked)}
          style={{ marginBottom: 12, fontSize: 12 }}
        >
          我已确认以上信息
        </Checkbox>
      </div>

      {/* 操作按钮 */}
      <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
        <Button size="small" icon={<CloseOutlined />} onClick={onCancel}>
          取消
        </Button>
        <Button
          size="small"
          type="primary"
          icon={<CheckOutlined />}
          disabled={!disclaimerAccepted}
          onClick={handleConfirm}
        >
          确认并生成
        </Button>
      </Space>
    </div>
  );
}
