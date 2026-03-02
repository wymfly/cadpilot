import { Typography } from 'antd';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';

const { Text } = Typography;

interface HeatmapLegendProps {
  type: 'wall_thickness' | 'overhang';
  min: number | null;
  max: number | null;
  threshold: number;
  verticesAtRisk: number;
  verticesAtRiskPercent: number;
}

const TYPE_LABELS: Record<string, string> = {
  wall_thickness: '壁厚',
  overhang: '悬垂',
};

export default function HeatmapLegend({
  type,
  min,
  max,
  threshold,
  verticesAtRisk,
  verticesAtRiskPercent,
}: HeatmapLegendProps) {
  const dt = useDesignTokens();
  const label = TYPE_LABELS[type] ?? type;
  const fmtVal = (v: number | null) => (v != null ? v.toFixed(2) : '—');

  return (
    <div
      style={{
        position: 'absolute',
        right: 16,
        top: '50%',
        transform: 'translateY(-50%)',
        background: dt.color.glassBg,
        backdropFilter: 'blur(12px)',
        borderRadius: dt.radius.md,
        padding: '12px 14px',
        boxShadow: dt.shadow.panel,
        zIndex: 10,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 6,
        minWidth: 72,
        fontFamily: dt.typography.fontMono,
      }}
    >
      <Text strong style={{ color: dt.color.textPrimary, fontSize: 12, marginBottom: 2 }}>
        {label}分析
      </Text>

      {/* Color bar with scale labels */}
      <div style={{ display: 'flex', alignItems: 'stretch', gap: 6 }}>
        {/* Scale labels */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            height: 120,
            textAlign: 'right',
          }}
        >
          <Text style={{ color: dt.color.success, fontSize: 10, lineHeight: 1 }}>
            {fmtVal(max)}
          </Text>
          <Text style={{ color: dt.color.warning, fontSize: 10, lineHeight: 1 }}>
            {threshold.toFixed(2)}
          </Text>
          <Text style={{ color: dt.color.error, fontSize: 10, lineHeight: 1 }}>
            {fmtVal(min)}
          </Text>
        </div>

        {/* Gradient bar */}
        <div
          style={{
            width: 14,
            height: 120,
            borderRadius: 3,
            background: 'linear-gradient(to top, #dc2626, #eab308 50%, #22c55e)',
            border: `1px solid ${dt.color.border}`,
          }}
        />
      </div>

      {/* Risk stats */}
      <Text style={{ color: dt.color.error, fontSize: 11, textAlign: 'center', marginTop: 2 }}>
        {verticesAtRiskPercent.toFixed(1)}% 超限 ({verticesAtRisk})
      </Text>
    </div>
  );
}
