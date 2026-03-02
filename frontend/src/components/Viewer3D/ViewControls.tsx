import { Button, Divider, Space, Tooltip } from 'antd';
import {
  BorderOutlined,
  GatewayOutlined,
  HeatMapOutlined,
} from '@ant-design/icons';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';

export type DfamMode = 'normal' | 'wall_thickness' | 'overhang';

export interface CameraPreset {
  label: string;
  position: [number, number, number];
}

const VIEW_PRESETS: CameraPreset[] = [
  { label: '正视', position: [0, 0, 5] },
  { label: '俯视', position: [0, 5, 0] },
  { label: '侧视', position: [5, 0, 0] },
  { label: '等轴', position: [3, 3, 3] },
];

const DFAM_BUTTONS: { mode: DfamMode; label: string }[] = [
  { mode: 'normal', label: '标准' },
  { mode: 'wall_thickness', label: '壁厚' },
  { mode: 'overhang', label: '悬垂' },
];

interface ViewControlsProps {
  wireframe: boolean;
  dfamMode?: DfamMode;
  dfamAvailable?: boolean;
  onWireframeToggle: () => void;
  onViewChange: (position: [number, number, number]) => void;
  onDfamModeChange?: (mode: DfamMode) => void;
}

export default function ViewControls({
  wireframe,
  dfamMode = 'normal',
  dfamAvailable,
  onWireframeToggle,
  onViewChange,
  onDfamModeChange,
}: ViewControlsProps) {
  const dt = useDesignTokens();
  return (
    <Space
      size={4}
      style={{
        position: 'absolute',
        bottom: 12,
        left: '50%',
        transform: 'translateX(-50%)',
        background: dt.color.glassBg,
        backdropFilter: 'blur(12px)',
        borderRadius: dt.radius.sm,
        padding: '4px 8px',
        boxShadow: dt.shadow.panel,
        zIndex: 10,
      }}
    >
      {VIEW_PRESETS.map((preset) => (
        <Tooltip key={preset.label} title={preset.label}>
          <Button
            size="small"
            onClick={() => onViewChange(preset.position)}
          >
            {preset.label}
          </Button>
        </Tooltip>
      ))}
      <Tooltip title={wireframe ? '切换实体' : '切换线框'}>
        <Button
          size="small"
          type={wireframe ? 'primary' : 'default'}
          icon={wireframe ? <GatewayOutlined /> : <BorderOutlined />}
          onClick={onWireframeToggle}
        />
      </Tooltip>

      {dfamAvailable && onDfamModeChange && (
        <>
          <Divider type="vertical" style={{ margin: '0 2px', borderColor: dt.color.border }} />
          <Tooltip title="DfAM 热力图">
            <HeatMapOutlined style={{ color: dt.color.textSecondary, fontSize: 14 }} />
          </Tooltip>
          {DFAM_BUTTONS.map((btn) => (
            <Tooltip key={btn.mode} title={btn.label}>
              <Button
                size="small"
                type={dfamMode === btn.mode ? 'primary' : 'default'}
                onClick={() => onDfamModeChange(btn.mode)}
              >
                {btn.label}
              </Button>
            </Tooltip>
          ))}
        </>
      )}
    </Space>
  );
}
