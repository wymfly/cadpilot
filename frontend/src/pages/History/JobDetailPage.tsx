import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Descriptions,
  Button,
  Tag,
  Space,
  Spin,
  Typography,
  Row,
  Col,
  message,
  Popconfirm,
} from 'antd';
import {
  ArrowLeftOutlined,
  ReloadOutlined,
  DeleteOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import Viewer3D from '../../components/Viewer3D/index.tsx';
import PrintReport from '../../components/PrintReport/index.tsx';
import api, { getJobDetail, deleteJob, regenerateJob, type JobDetail } from '../../services/api.ts';

const { Title, Text } = Typography;

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

export default function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchJob = useCallback(async () => {
    if (!jobId) return;
    setLoading(true);
    try {
      const data = await getJobDetail(jobId);
      setJob(data);
    } catch {
      message.error('加载失败');
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    fetchJob();
  }, [fetchJob]);

  const handleDelete = async () => {
    if (!jobId) return;
    try {
      await deleteJob(jobId);
      message.success('已删除');
      navigate('/history');
    } catch {
      message.error('删除失败');
    }
  };

  const handleRegenerate = async () => {
    if (!jobId) return;
    try {
      const data = await regenerateJob(jobId);
      navigate(`/generate?jobId=${data.job_id}`);
    } catch {
      message.error('重新生成失败');
    }
  };

  const handleDownload = async (format: string) => {
    if (!jobId) return;
    try {
      const { data } = await api.post('/export', { job_id: jobId, config: { format } }, { responseType: 'blob' });
      const ext = format === 'gltf' ? 'glb' : format;
      const url = URL.createObjectURL(data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `model.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      message.error('下载失败');
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!job) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Text type="secondary">记录未找到</Text>
      </div>
    );
  }

  const statusInfo = STATUS_TAG_MAP[job.status] ?? { color: 'default', label: job.status };
  const modelUrl = job.result?.model_url ?? null;

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/history')}>
            返回列表
          </Button>
          <Title level={4} style={{ margin: 0 }}>
            {job.input_text || '(无标题)'}
          </Title>
          <Tag color={statusInfo.color}>{statusInfo.label}</Tag>
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={handleRegenerate}>
            改参数重生成
          </Button>
          <Popconfirm title="确定删除？" onConfirm={handleDelete}>
            <Button danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      </div>

      <Row gutter={24}>
        {/* Left: 3D Viewer + Downloads */}
        <Col xs={24} lg={14}>
          <div style={{ height: 500, marginBottom: 16 }}>
            <Viewer3D modelUrl={modelUrl} />
          </div>

          {job.status === 'completed' && (
            <Space style={{ marginBottom: 16 }}>
              <Button icon={<DownloadOutlined />} type="primary" onClick={() => handleDownload('step')}>
                STEP
              </Button>
              <Button icon={<DownloadOutlined />} onClick={() => handleDownload('stl')}>
                STL
              </Button>
              <Button icon={<DownloadOutlined />} onClick={() => handleDownload('3mf')}>
                3MF
              </Button>
              <Button icon={<DownloadOutlined />} onClick={() => handleDownload('gltf')}>
                GLB
              </Button>
            </Space>
          )}
        </Col>

        {/* Right: Details + PrintReport */}
        <Col xs={24} lg={10}>
          <Card size="small" title="基本信息" style={{ marginBottom: 16 }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="Job ID">
                <Text copyable style={{ fontSize: 12 }}>{job.job_id}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="输入类型">
                {job.input_type === 'text' ? '文本生成' : '图纸生成'}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {new Date(job.created_at).toLocaleString('zh-CN')}
              </Descriptions.Item>
              {job.error && (
                <Descriptions.Item label="错误">
                  <Text type="danger">{job.error}</Text>
                </Descriptions.Item>
              )}
            </Descriptions>
          </Card>

          {/* Printability Report */}
          {job.printability_result && (
            <div style={{ marginBottom: 16 }}>
              <PrintReport results={job.printability_result} />
            </div>
          )}

          {/* Parameters */}
          {job.precise_spec && (
            <Card size="small" title="参数详情" style={{ marginBottom: 16 }}>
              <pre style={{ fontSize: 12, margin: 0, whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                {JSON.stringify(job.precise_spec, null, 2)}
              </pre>
            </Card>
          )}
        </Col>
      </Row>
    </div>
  );
}
