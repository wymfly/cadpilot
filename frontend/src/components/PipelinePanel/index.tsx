import { Tabs } from 'antd';
import {
  NodeIndexOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';
import PipelineDAG from '../PipelineDAG/index.tsx';
import type { JobEvent } from '../../hooks/useJobEvents.ts';

interface PipelinePanelProps {
  /** The existing workflow progress component (Steps) */
  progressView: React.ReactNode;
  /** Input type for DAG path filtering */
  inputType: string | null;
  /** SSE events for DAG node state tracking */
  events: JobEvent[];
}

export default function PipelinePanel({
  progressView,
  inputType,
  events,
}: PipelinePanelProps) {
  const dt = useDesignTokens();
  return (
    <Tabs
      defaultActiveKey="progress"
      size="small"
      style={{ color: dt.color.textPrimary }}
      items={[
        {
          key: 'progress',
          label: (
            <span>
              <UnorderedListOutlined /> 进度
            </span>
          ),
          children: progressView,
        },
        {
          key: 'dag',
          label: (
            <span>
              <NodeIndexOutlined /> 管道
            </span>
          ),
          children: (
            <PipelineDAG inputType={inputType} events={events} />
          ),
        },
      ]}
    />
  );
}
