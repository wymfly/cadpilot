import { useState, useMemo } from 'react';
import {
  Card,
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
} from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import type { DrawingSpec, DrawingSpecFeature } from '../../types/generate.ts';

const { Text } = Typography;

const PART_TYPE_OPTIONS = [
  { value: 'ROTATIONAL', label: '回转体' },
  { value: 'ROTATIONAL_STEPPED', label: '阶梯回转体' },
  { value: 'PLATE', label: '板件' },
  { value: 'BRACKET', label: '支架' },
  { value: 'HOUSING', label: '壳体' },
  { value: 'GEAR', label: '齿轮' },
  { value: 'GENERAL', label: '通用' },
];

const BASE_BODY_METHOD_OPTIONS = [
  { value: 'revolve', label: '回转 (Revolve)' },
  { value: 'extrude', label: '拉伸 (Extrude)' },
  { value: 'loft', label: '放样 (Loft)' },
  { value: 'sweep', label: '扫掠 (Sweep)' },
  { value: 'shell', label: '抽壳 (Shell)' },
];

interface DrawingSpecReviewProps {
  drawingSpec: DrawingSpec;
  onConfirm: (spec: DrawingSpec, disclaimerAccepted: boolean) => void;
  onCancel: () => void;
}

export default function DrawingSpecReview({
  drawingSpec,
  onConfirm,
  onCancel,
}: DrawingSpecReviewProps) {
  const [form] = Form.useForm();
  const [disclaimerAccepted, setDisclaimerAccepted] = useState(false);
  const [partType, setPartType] = useState(drawingSpec.part_type);
  const [baseBodyMethod, setBaseBodyMethod] = useState(drawingSpec.base_body.method);
  const [features, setFeatures] = useState<DrawingSpecFeature[]>(drawingSpec.features);

  const confidence = drawingSpec.confidence ?? 0;

  const confidenceTag = useMemo(() => {
    if (confidence >= 0.8) {
      return <Tag color="green">AI 置信度: {(confidence * 100).toFixed(0)}%</Tag>;
    }
    if (confidence >= 0.5) {
      return <Tag color="orange">AI 置信度: {(confidence * 100).toFixed(0)}%</Tag>;
    }
    return <Tag color="red">AI 置信度: {(confidence * 100).toFixed(0)}%</Tag>;
  }, [confidence]);

  const handleConfirm = () => {
    const dims = form.getFieldsValue();
    const confirmedSpec: DrawingSpec = {
      part_type: partType,
      overall_dimensions: dims,
      base_body: {
        ...drawingSpec.base_body,
        method: baseBodyMethod,
      },
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
    <Card
      title={
        <Space>
          <span>AI 图纸分析结果确认</span>
          {confidenceTag}
        </Space>
      }
    >
      {/* Part type selector */}
      <div style={{ marginBottom: 16 }}>
        <Text strong style={{ marginRight: 8 }}>零件类型</Text>
        <Select
          value={partType}
          onChange={setPartType}
          options={PART_TYPE_OPTIONS}
          style={{ width: 200 }}
        />
      </div>

      {/* Editable dimensions */}
      <Card size="small" title="总体尺寸" style={{ marginBottom: 16 }}>
        <Form form={form} layout="inline" initialValues={drawingSpec.overall_dimensions}>
          {Object.entries(drawingSpec.overall_dimensions).map(([key]) => (
            <Form.Item key={key} name={key} label={key}>
              <InputNumber precision={2} min={0} addonAfter="mm" />
            </Form.Item>
          ))}
        </Form>
      </Card>

      {/* Base body params */}
      <Card size="small" title="基体参数" style={{ marginBottom: 16 }}>
        <div>
          <Text strong style={{ marginRight: 8 }}>建模方法</Text>
          <Select
            value={baseBodyMethod}
            onChange={setBaseBodyMethod}
            options={BASE_BODY_METHOD_OPTIONS}
            style={{ width: 200 }}
          />
        </div>
      </Card>

      {/* Features list */}
      {features.length > 0 && (
        <Collapse
          style={{ marginBottom: 16 }}
          items={features.map((feat, i) => ({
            key: i,
            label: (
              <Space>
                <Text>{feat.type}</Text>
                <Tag>{Object.keys(feat).filter((k) => k !== 'type').length} 个参数</Tag>
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
              <pre style={{ fontSize: 12, margin: 0, whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(feat, null, 2)}
              </pre>
            ),
          }))}
        />
      )}

      {/* Notes */}
      {drawingSpec.notes.length > 0 && (
        <Card size="small" title="备注" style={{ marginBottom: 16 }}>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {drawingSpec.notes.map((note, i) => (
              <li key={i}><Text type="secondary">{note}</Text></li>
            ))}
          </ul>
        </Card>
      )}

      {/* Disclaimer */}
      <Alert
        type="warning"
        message="AI 识别结果仅供参考"
        description="AI 从工程图纸中提取的尺寸和特征可能存在误差，请务必核对关键参数。确认后将基于这些参数生成 3D 模型。"
        style={{ marginBottom: 12 }}
      />
      <Checkbox
        checked={disclaimerAccepted}
        onChange={(e) => setDisclaimerAccepted(e.target.checked)}
        style={{ marginBottom: 16 }}
      >
        我已确认以上信息，了解 AI 识别可能存在误差
      </Checkbox>

      {/* Actions */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <Button icon={<CloseOutlined />} onClick={onCancel}>
          取消
        </Button>
        <Button
          type="primary"
          icon={<CheckOutlined />}
          disabled={!disclaimerAccepted}
          onClick={handleConfirm}
        >
          确认并生成
        </Button>
      </div>
    </Card>
  );
}
