import { Card, Descriptions, Tag } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';
import type { MeshStats } from '../../types/organic.ts';

interface MeshStatsCardProps {
  stats: MeshStats;
}

export default function MeshStatsCard({ stats }: MeshStatsCardProps) {
  const bboxStr = Object.entries(stats.bounding_box)
    .map(([k, v]) => `${k}: ${v.toFixed(1)}`)
    .join(', ');

  return (
    <Card size="small" title="网格统计" style={{ marginBottom: 16 }}>
      <Descriptions column={2} size="small">
        <Descriptions.Item label="顶点数">
          {stats.vertex_count.toLocaleString()}
        </Descriptions.Item>
        <Descriptions.Item label="面数">
          {stats.face_count.toLocaleString()}
        </Descriptions.Item>
        <Descriptions.Item label="水密性">
          {stats.is_watertight ? (
            <Tag icon={<CheckCircleOutlined />} color="success">
              水密
            </Tag>
          ) : (
            <Tag icon={<CloseCircleOutlined />} color="error">
              非水密
            </Tag>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="体积">
          {stats.volume_cm3 != null ? `${stats.volume_cm3.toFixed(2)} cm³` : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="包围盒" span={2}>
          {bboxStr}
        </Descriptions.Item>
        {stats.repairs_applied.length > 0 && (
          <Descriptions.Item label="修复操作" span={2}>
            {stats.repairs_applied.join(', ')}
          </Descriptions.Item>
        )}
        {stats.boolean_cuts_applied > 0 && (
          <Descriptions.Item label="布尔切割">
            {stats.boolean_cuts_applied} 次
          </Descriptions.Item>
        )}
      </Descriptions>
    </Card>
  );
}
