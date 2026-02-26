import { Slider, InputNumber, Space, Tooltip, Typography } from 'antd';
import { InfoCircleOutlined } from '@ant-design/icons';
import type { ParamDefinition } from '../../types/template.ts';
import type { ParamRecommendation } from '../../types/standard.ts';

const { Text } = Typography;

interface ParamSliderProps {
  param: ParamDefinition;
  value: number;
  recommendation?: ParamRecommendation;
  onChange: (value: number) => void;
}

export default function ParamSlider({
  param,
  value,
  recommendation,
  onChange,
}: ParamSliderProps) {
  const min = param.range_min ?? 0;
  const max = param.range_max ?? 1000;
  const step = max - min > 100 ? 1 : 0.1;

  return (
    <div>
      <Space size={4} style={{ marginBottom: 4 }}>
        <Text strong>{param.display_name}</Text>
        {param.unit && <Text type="secondary">({param.unit})</Text>}
        {recommendation && (
          <Tooltip
            title={
              <span>
                推荐值: {recommendation.value} {recommendation.unit}
                <br />
                {recommendation.reason}
                {recommendation.source && (
                  <>
                    <br />
                    来源: {recommendation.source}
                  </>
                )}
              </span>
            }
          >
            <InfoCircleOutlined style={{ color: '#1677ff', cursor: 'pointer' }} />
          </Tooltip>
        )}
      </Space>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <Slider
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={onChange}
          style={{ flex: 1 }}
          marks={
            recommendation
              ? { [recommendation.value]: { label: '推荐', style: { fontSize: 10 } } }
              : undefined
          }
        />
        <InputNumber
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(v) => v !== null && onChange(v)}
          style={{ width: 100 }}
          addonAfter={param.unit || undefined}
        />
      </div>
    </div>
  );
}
