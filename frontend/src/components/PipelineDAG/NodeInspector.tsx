import { Drawer, Descriptions, Tag, Divider } from 'antd';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';
import ReasoningCard from './ReasoningCard.tsx';
import type { NodeStatus } from './NodeCard.tsx';

export interface NodeInspectorData {
  nodeId: string;
  label: string;
  status: NodeStatus;
  elapsedMs?: number;
  reasoning?: Record<string, string> | null;
  outputsSummary?: Record<string, unknown> | null;
  error?: string;
}

interface NodeInspectorProps {
  open: boolean;
  data: NodeInspectorData | null;
  onClose: () => void;
}

const STATUS_LABELS: Record<NodeStatus, { text: string; color: string }> = {
  pending: { text: '等待中', color: 'default' },
  running: { text: '运行中', color: 'processing' },
  completed: { text: '已完成', color: 'success' },
  failed: { text: '失败', color: 'error' },
};

export default function NodeInspector({ open, data, onClose }: NodeInspectorProps) {
  const dt = useDesignTokens();
  if (!data) return null;

  const statusInfo = STATUS_LABELS[data.status];

  return (
    <Drawer
      title={data.label}
      open={open}
      onClose={onClose}
      width={420}
      styles={{
        body: { padding: '16px', background: dt.color.surface1, fontFamily: dt.typography.fontMono },
        header: { background: dt.color.surface2 },
      }}
    >
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="节点">
          <code>{data.nodeId}</code>
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={statusInfo.color}>{statusInfo.text}</Tag>
        </Descriptions.Item>
        {data.elapsedMs != null && (
          <Descriptions.Item label="耗时">
            {data.elapsedMs < 1000
              ? `${data.elapsedMs}ms`
              : `${(data.elapsedMs / 1000).toFixed(1)}s`}
          </Descriptions.Item>
        )}
        {data.error && (
          <Descriptions.Item label="错误">
            <Tag color="error">{data.error}</Tag>
          </Descriptions.Item>
        )}
      </Descriptions>

      {data.outputsSummary && Object.keys(data.outputsSummary).length > 0 && (
        <>
          <Divider titlePlacement="left" plain>
            输出摘要
          </Divider>
          <Descriptions column={1} size="small" bordered>
            {Object.entries(data.outputsSummary).map(([key, value]) => (
              <Descriptions.Item key={key} label={key}>
                {typeof value === 'string'
                  ? value
                  : JSON.stringify(value, null, 2).slice(0, 200)}
              </Descriptions.Item>
            ))}
          </Descriptions>
        </>
      )}

      <Divider titlePlacement="left" plain>
        推理过程
      </Divider>
      <ReasoningCard reasoning={data.reasoning ?? null} />
    </Drawer>
  );
}
