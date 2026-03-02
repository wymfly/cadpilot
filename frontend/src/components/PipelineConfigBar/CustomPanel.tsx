import { Switch, Select, Space, Row, Col, Typography, Tag } from 'antd';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';
import type { PipelineNodeDescriptor, NodeLevelConfig } from '../../types/pipeline.ts';

const { Text } = Typography;

interface CustomPanelProps {
  descriptors: PipelineNodeDescriptor[];
  config: Record<string, NodeLevelConfig>;
  onChange: (nodeConfig: Record<string, NodeLevelConfig>) => void;
}

/** Nodes that are always enabled and cannot be toggled */
const NON_TOGGLEABLE = new Set(['create_job', 'confirm_with_user', 'finalize']);

/** Group label mapping */
const GROUP_LABELS: Record<string, string> = {
  analysis: '分析',
  generation: '生成',
  postprocess: '后处理',
};

function inferGroup(desc: PipelineNodeDescriptor): string {
  if (desc.is_entry || desc.is_terminal || desc.supports_hitl) return 'system';
  if (desc.name.startsWith('analyze_')) return 'analysis';
  if (desc.name.startsWith('generate_')) return 'generation';
  return 'postprocess';
}

export default function CustomPanel({ descriptors, config, onChange }: CustomPanelProps) {
  const dt = useDesignTokens();
  // Group configurable nodes
  const groups: Record<string, PipelineNodeDescriptor[]> = {};
  for (const desc of descriptors) {
    const group = inferGroup(desc);
    if (group === 'system') continue; // skip non-configurable nodes
    if (!groups[group]) groups[group] = [];
    groups[group].push(desc);
  }

  const handleToggle = (nodeName: string, enabled: boolean) => {
    const updated = { ...config };
    updated[nodeName] = { ...updated[nodeName], enabled };
    onChange(updated);
  };

  const handleStrategy = (nodeName: string, strategy: string) => {
    const updated = { ...config };
    updated[nodeName] = { ...updated[nodeName], strategy };
    onChange(updated);
  };

  return (
    <div style={{ padding: '12px 0' }}>
      {Object.entries(groups).map(([group, nodes]) => (
        <div key={group} style={{ marginBottom: 16 }}>
          <Text strong style={{ display: 'block', marginBottom: 8, color: dt.color.textSecondary }}>
            {GROUP_LABELS[group] ?? group}
          </Text>
          <Row gutter={[16, 12]}>
            {nodes.map((desc) => {
              const nodeConf = config[desc.name] ?? {};
              const enabled = nodeConf.enabled !== false;
              const canToggle = !NON_TOGGLEABLE.has(desc.name);

              return (
                <Col key={desc.name} span={24}>
                  <Space size={8} align="start" style={{ width: '100%' }}>
                    {canToggle && (
                      <Switch
                        size="small"
                        checked={enabled}
                        onChange={(val) => handleToggle(desc.name, val)}
                      />
                    )}
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <Text style={{ opacity: enabled ? 1 : 0.5 }}>
                          {desc.display_name}
                        </Text>
                        {desc.non_fatal && (
                          <Tag color="default" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                            可选
                          </Tag>
                        )}
                      </div>
                      {desc.strategies.length > 1 && enabled && (
                        <Select
                          size="small"
                          value={nodeConf.strategy ?? desc.default_strategy ?? desc.strategies[0]}
                          onChange={(val) => handleStrategy(desc.name, val)}
                          options={desc.strategies.map((s) => ({ label: s, value: s }))}
                          style={{ width: '100%', marginTop: 4 }}
                        />
                      )}
                    </div>
                  </Space>
                </Col>
              );
            })}
          </Row>
        </div>
      ))}
    </div>
  );
}
