import { Form, InputNumber, Input, Switch, Tag, Typography } from 'antd';
import type { ParamDefinition } from '../../types/template.ts';
import type { ParamRecommendation } from '../../types/standard.ts';
import ParamSlider from './ParamSlider.tsx';

const { Text } = Typography;

interface ParamFieldProps {
  param: ParamDefinition;
  value: number | string | boolean | undefined;
  recommendation?: ParamRecommendation;
  onChange: (name: string, value: number | string | boolean) => void;
}

export default function ParamField({
  param,
  value,
  recommendation,
  onChange,
}: ParamFieldProps) {
  // Numeric types with range → use slider
  if (
    (param.param_type === 'float' || param.param_type === 'int') &&
    param.range_min != null &&
    param.range_max != null
  ) {
    return (
      <Form.Item style={{ marginBottom: 16 }}>
        <ParamSlider
          param={param}
          value={typeof value === 'number' ? value : (param.default as number) ?? 0}
          recommendation={recommendation}
          onChange={(v) => onChange(param.name, v)}
        />
      </Form.Item>
    );
  }

  // Numeric types without range → input number
  if (param.param_type === 'float' || param.param_type === 'int') {
    return (
      <Form.Item
        label={
          <>
            {param.display_name}
            {param.unit && <Text type="secondary"> ({param.unit})</Text>}
          </>
        }
        style={{ marginBottom: 16 }}
        extra={
          recommendation && (
            <Tag color="blue" style={{ marginTop: 4 }}>
              推荐: {recommendation.value} {recommendation.unit} — {recommendation.reason}
            </Tag>
          )
        }
      >
        <InputNumber
          value={typeof value === 'number' ? value : undefined}
          onChange={(v) => v !== null && onChange(param.name, v as number)}
          step={param.param_type === 'int' ? 1 : 0.1}
          style={{ width: '100%' }}
        />
      </Form.Item>
    );
  }

  // Boolean type → switch
  if (param.param_type === 'bool') {
    return (
      <Form.Item label={param.display_name} style={{ marginBottom: 16 }}>
        <Switch
          checked={typeof value === 'boolean' ? value : false}
          onChange={(checked) => onChange(param.name, checked)}
        />
      </Form.Item>
    );
  }

  // String type → text input
  return (
    <Form.Item label={param.display_name} style={{ marginBottom: 16 }}>
      <Input
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(param.name, e.target.value)}
      />
    </Form.Item>
  );
}
