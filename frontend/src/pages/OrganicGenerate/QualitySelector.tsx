import { Radio, Select, Space, Typography } from 'antd';
import type { QualityMode, ProviderPreference } from '../../types/organic.ts';

const { Text } = Typography;

const QUALITY_OPTIONS: { label: string; value: QualityMode }[] = [
  { label: '草稿', value: 'draft' },
  { label: '标准', value: 'standard' },
  { label: '高质量', value: 'high' },
];

const PROVIDER_OPTIONS: { label: string; value: ProviderPreference }[] = [
  { label: '自动选择', value: 'auto' },
  { label: 'Tripo3D', value: 'tripo3d' },
  { label: 'Hunyuan3D', value: 'hunyuan3d' },
];

interface QualitySelectorProps {
  qualityMode: QualityMode;
  onQualityChange: (mode: QualityMode) => void;
  provider: ProviderPreference;
  onProviderChange: (provider: ProviderPreference) => void;
  disabled?: boolean;
}

export default function QualitySelector({
  qualityMode,
  onQualityChange,
  provider,
  onProviderChange,
  disabled,
}: QualitySelectorProps) {
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <div>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>
          生成质量
        </Text>
        <Radio.Group
          value={qualityMode}
          onChange={(e) => onQualityChange(e.target.value)}
          optionType="button"
          buttonStyle="solid"
          options={QUALITY_OPTIONS}
          disabled={disabled}
        />
      </div>
      <div>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>
          生成引擎
        </Text>
        <Select
          value={provider}
          onChange={onProviderChange}
          options={PROVIDER_OPTIONS}
          disabled={disabled}
          style={{ width: 160 }}
        />
      </div>
    </Space>
  );
}
