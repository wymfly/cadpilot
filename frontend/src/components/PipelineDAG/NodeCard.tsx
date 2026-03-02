import { memo, type ReactNode } from 'react';
import { Handle, Position } from '@xyflow/react';
import { Tag } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';

export type NodeStatus = 'pending' | 'running' | 'completed' | 'failed';

interface NodeCardData {
  label: string;
  group: string;
  status?: NodeStatus;
  elapsedMs?: number;
  strategy?: string | null;
  nonFatal?: boolean;
}

const STATUS_CONFIG: Record<NodeStatus, { color: string; icon: ReactNode }> = {
  pending: { color: 'default', icon: <ClockCircleOutlined /> },
  running: { color: 'processing', icon: <LoadingOutlined /> },
  completed: { color: 'success', icon: <CheckCircleOutlined /> },
  failed: { color: 'error', icon: <CloseCircleOutlined /> },
};

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function NodeCard({ data }: { data: NodeCardData }) {
  const status = data.status || 'pending';
  const config = STATUS_CONFIG[status];
  const dt = useDesignTokens();

  const borderColor = status === 'running' ? dt.color.primary
    : status === 'failed' ? dt.color.error
    : dt.color.border;
  const bgColor = status === 'failed'
    ? (dt.isDark ? 'rgba(255,51,51,0.08)' : 'rgba(229,48,48,0.04)')
    : dt.color.surface2;

  return (
    <div
      style={{
        padding: '8px 16px',
        borderRadius: dt.radius.md,
        border: `2px solid ${borderColor}`,
        background: bgColor,
        minWidth: 140,
        textAlign: 'center',
        cursor: status !== 'pending' ? 'pointer' : 'default',
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'center' }}>
        <Tag color={config.color} icon={config.icon} style={{ margin: 0 }}>
          {data.label}
        </Tag>
      </div>
      {data.strategy && (
        <div style={{ fontSize: 10, color: dt.color.textTertiary, marginTop: 2, fontFamily: dt.typography.fontMono }}>
          {data.strategy}
        </div>
      )}
      {data.elapsedMs != null && (
        <div style={{ fontSize: 11, color: dt.color.textSecondary, marginTop: 4, fontFamily: dt.typography.fontMono }}>
          {formatMs(data.elapsedMs)}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

export default memo(NodeCard);
