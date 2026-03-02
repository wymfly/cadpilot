import { Radio, Select, Space, Tooltip, Typography } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import type { QualityMode, ProviderPreference } from '../../types/organic.ts';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';

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

function HelpTip({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Tooltip
      title={<div style={{ maxWidth: 300 }}><div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>{children}</div>}
      placement="top"
    >
      <QuestionCircleOutlined style={{ color: 'inherit', marginLeft: 4, cursor: 'help' }} />
    </Tooltip>
  );
}

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
  const dt = useDesignTokens();
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <Text strong>生成质量</Text>
          <HelpTip title="生成质量">
            <div>控制 3D 模型的精细程度，质量越高耗时越长。</div>
            <table style={{ marginTop: 8, width: '100%', fontSize: 12, lineHeight: 1.6 }}>
              <tbody>
                <tr>
                  <td style={{ color: dt.color.primary, paddingRight: 8, whiteSpace: 'nowrap' }}>草稿</td>
                  <td>快速预览，约 30-60 秒。面数较少，适合快速验证创意方向</td>
                </tr>
                <tr>
                  <td style={{ color: dt.color.primary, paddingRight: 8, whiteSpace: 'nowrap' }}>标准</td>
                  <td>均衡模式，约 1-2 分钟。细节适中，适合大多数场景</td>
                </tr>
                <tr>
                  <td style={{ color: dt.color.primary, paddingRight: 8, whiteSpace: 'nowrap' }}>高质量</td>
                  <td>最高精度，约 2-5 分钟。细节丰富，适合最终成品</td>
                </tr>
              </tbody>
            </table>
            <div style={{ marginTop: 4, color: dt.color.success }}>默认: 标准</div>
          </HelpTip>
        </div>
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
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <Text strong>生成引擎</Text>
          <HelpTip title="生成引擎">
            <div>选择后端 3D 生成服务。</div>
            <table style={{ marginTop: 8, width: '100%', fontSize: 12, lineHeight: 1.6 }}>
              <tbody>
                <tr>
                  <td style={{ color: dt.color.primary, paddingRight: 8, whiteSpace: 'nowrap' }}>自动选择</td>
                  <td>按可用性自动选择最佳引擎（推荐）</td>
                </tr>
                <tr>
                  <td style={{ color: dt.color.primary, paddingRight: 8, whiteSpace: 'nowrap' }}>Tripo3D</td>
                  <td>速度快，擅长日常物品和角色模型</td>
                </tr>
                <tr>
                  <td style={{ color: dt.color.primary, paddingRight: 8, whiteSpace: 'nowrap' }}>Hunyuan3D</td>
                  <td>腾讯出品，擅长复杂几何和工业造型</td>
                </tr>
              </tbody>
            </table>
            <div style={{ marginTop: 4, color: dt.color.success }}>默认: 自动选择</div>
          </HelpTip>
        </div>
        <Select
          value={provider}
          onChange={onProviderChange}
          options={PROVIDER_OPTIONS}
          disabled={disabled}
          style={{ width: '100%' }}
        />
      </div>
    </Space>
  );
}
