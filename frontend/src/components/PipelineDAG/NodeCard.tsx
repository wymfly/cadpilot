import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { Tag } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';

export type NodeStatus = 'pending' | 'running' | 'completed' | 'failed';

interface NodeCardData {
  label: string;
  group: string;
  status?: NodeStatus;
  elapsedMs?: number;
}

const STATUS_CONFIG: Record<NodeStatus, { color: string; icon: React.ReactNode }> = {
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

  return (
    <div
      style={{
        padding: '8px 16px',
        borderRadius: 8,
        border: `2px solid ${status === 'running' ? '#1677ff' : '#d9d9d9'}`,
        background: status === 'failed' ? '#fff2f0' : '#fff',
        minWidth: 140,
        textAlign: 'center',
        cursor: status === 'completed' || status === 'failed' ? 'pointer' : 'default',
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'center' }}>
        <Tag color={config.color} icon={config.icon} style={{ margin: 0 }}>
          {data.label}
        </Tag>
      </div>
      {data.elapsedMs != null && (
        <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
          {formatMs(data.elapsedMs)}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

export default memo(NodeCard);
