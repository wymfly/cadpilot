import { useState, useEffect, useCallback } from 'react';
import { Card, Row, Col, Tag, Pagination, Select, Typography, Empty, Spin, message } from 'antd';
import { ClockCircleOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { listJobs, type PaginatedJobsResponse } from '../../services/api.ts';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';

const { Title, Text, Paragraph } = Typography;

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

const STATUS_FILTER_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'generating', label: '生成中' },
];

const TYPE_FILTER_OPTIONS = [
  { value: '', label: '全部类型' },
  { value: 'text', label: '文本生成' },
  { value: 'drawing', label: '图纸生成' },
];

export default function HistoryPage() {
  const navigate = useNavigate();
  const dt = useDesignTokens();
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<PaginatedJobsResponse | null>(null);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listJobs({
        page,
        page_size: 12,
        status: statusFilter || undefined,
        input_type: typeFilter || undefined,
      });
      setData(result);
    } catch {
      message.error('加载历史记录失败');
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, typeFilter]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>零件库</Title>
          <Paragraph type="secondary" style={{ margin: 0 }}>查看历史生成记录</Paragraph>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Select
            value={statusFilter}
            onChange={(v) => { setStatusFilter(v); setPage(1); }}
            options={STATUS_FILTER_OPTIONS}
            style={{ width: 120 }}
          />
          <Select
            value={typeFilter}
            onChange={(v) => { setTypeFilter(v); setPage(1); }}
            options={TYPE_FILTER_OPTIONS}
            style={{ width: 120 }}
          />
        </div>
      </div>

      <Spin spinning={loading}>
        {data && data.items.length > 0 ? (
          <>
            <Row gutter={[16, 16]}>
              {data.items.map((job) => {
                const statusInfo = STATUS_TAG_MAP[job.status] ?? { color: 'default', label: job.status };
                return (
                  <Col key={job.job_id} xs={24} sm={12} md={8} lg={6}>
                    <Card
                      hoverable
                      size="small"
                      onClick={() => navigate(`/history/${job.job_id}`)}
                      cover={
                        <div style={{
                          height: 120,
                          background: dt.color.surface2,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: dt.color.textTertiary,
                          fontSize: 13,
                        }}>
                          3D 预览
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
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <Tag color={statusInfo.color}>{statusInfo.label}</Tag>
                            <Text type="secondary" style={{ fontSize: 11 }}>
                              <ClockCircleOutlined style={{ marginRight: 4 }} />
                              {formatTime(job.created_at)}
                            </Text>
                          </div>
                        }
                      />
                    </Card>
                  </Col>
                );
              })}
            </Row>

            <div style={{ textAlign: 'center', marginTop: 24 }}>
              <Pagination
                current={page}
                total={data.total}
                pageSize={12}
                onChange={setPage}
                showSizeChanger={false}
              />
            </div>
          </>
        ) : (
          !loading && <Empty description="暂无生成记录" />
        )}
      </Spin>
    </div>
  );
}
