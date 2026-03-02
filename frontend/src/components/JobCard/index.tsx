import { Card, Tag, Typography, Badge } from 'antd';
import { ClockCircleOutlined, CheckCircleFilled, WarningFilled } from '@ant-design/icons';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';
import type { JobSummary } from '../../services/api.ts';

const { Text } = Typography;

const STATUS_TAG_MAP: Record<string, { color: string; label: string }> = {
  completed: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
  generating: { color: 'processing', label: '生成中' },
  created: { color: 'default', label: '已创建' },
  awaiting_confirmation: { color: 'warning', label: '待确认' },
  awaiting_drawing_confirmation: { color: 'warning', label: '待图纸确认' },
  refining: { color: 'processing', label: '优化中' },
  validation_failed: { color: 'error', label: '校验失败' },
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  return (
    d.toLocaleDateString('zh-CN') +
    ' ' +
    d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  );
}

export interface JobCardProps {
  job: JobSummary;
  onClick?: () => void;
}

export default function JobCard({ job, onClick }: JobCardProps) {
  const dt = useDesignTokens();
  const statusInfo = STATUS_TAG_MAP[job.status] ?? {
    color: 'default',
    label: job.status,
  };

  const isPrintable = job.result && 'printable' in job.result
    ? (job.result.printable as boolean)
    : null;

  return (
    <Badge.Ribbon
      text={isPrintable === true ? '可打印' : isPrintable === false ? '不可打印' : undefined}
      color={isPrintable === true ? 'green' : isPrintable === false ? 'orange' : undefined}
      style={{ display: isPrintable == null ? 'none' : undefined }}
    >
      <Card
        hoverable
        size="small"
        onClick={onClick}
        style={{ boxShadow: dt.shadow.hover }}
        cover={
          <div
            style={{
              height: 140,
              background: `linear-gradient(135deg, ${dt.color.surface2} 0%, ${dt.color.surface3} 100%)`,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              color: dt.color.textTertiary,
              fontSize: 13,
              gap: 4,
            }}
          >
            {job.status === 'completed' ? (
              <>
                <CheckCircleFilled style={{ fontSize: 28, color: dt.color.success }} />
                <span>3D 模型</span>
              </>
            ) : job.status === 'failed' ? (
              <>
                <WarningFilled style={{ fontSize: 28, color: dt.color.error }} />
                <span>生成失败</span>
              </>
            ) : (
              <span>3D 预览</span>
            )}
          </div>
        }
      >
        <Card.Meta
          title={
            <Text ellipsis style={{ fontSize: 13 }}>
              {job.input_text || '(无标题)'}
            </Text>
          }
          description={
            <div>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 4,
                }}
              >
                <Tag color={statusInfo.color} style={{ fontSize: 11 }}>
                  {statusInfo.label}
                </Tag>
                <Tag style={{ fontSize: 11 }}>
                  {job.input_type === 'text' ? '文本' : '图纸'}
                </Tag>
              </div>
              <Text
                type="secondary"
                style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}
              >
                <ClockCircleOutlined />
                {formatTime(job.created_at)}
              </Text>
            </div>
          }
        />
      </Card>
    </Badge.Ribbon>
  );
}
