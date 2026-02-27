import { useState, useEffect, useRef, useCallback } from 'react';
import { Typography, Select, Button, Progress, Card, Space, message } from 'antd';
import { PlayCircleOutlined, ArrowLeftOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { getBenchmarkDatasets, createSSEConnection } from '../../services/api.ts';
import type { BenchmarkProgressEvent } from '../../types/benchmark.ts';

const { Title, Text } = Typography;

export default function RunBenchmark() {
  const navigate = useNavigate();
  const [datasets, setDatasets] = useState<string[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<string>('');
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<BenchmarkProgressEvent | null>(null);
  const [completed, setCompleted] = useState(false);
  const [completedRunId, setCompletedRunId] = useState<string>('');
  const sseRef = useRef<EventSource | null>(null);

  useEffect(() => {
    getBenchmarkDatasets()
      .then((ds) => {
        setDatasets(ds);
        if (ds.length > 0) setSelectedDataset(ds[0]);
      })
      .catch(() => {
        const fallback = ['v1'];
        setDatasets(fallback);
        setSelectedDataset(fallback[0]);
      });
  }, []);

  useEffect(() => {
    return () => {
      if (sseRef.current) {
        sseRef.current.close();
      }
    };
  }, []);

  const handleRun = useCallback(() => {
    if (!selectedDataset) {
      message.warning('请选择数据集');
      return;
    }

    setRunning(true);
    setProgress(null);
    setCompleted(false);

    const source = createSSEConnection(
      `/api/benchmark/run?dataset=${encodeURIComponent(selectedDataset)}`,
      {
        onProgress: (data) => {
          setProgress(data as BenchmarkProgressEvent);
        },
        onComplete: (data) => {
          setRunning(false);
          setCompleted(true);
          setCompletedRunId((data as Record<string, unknown>).run_id as string);
          source.close();
          message.success('评测完成！');
        },
        onError: (data) => {
          setRunning(false);
          source.close();
          message.error(`评测失败: ${(data as Record<string, unknown>).message as string}`);
        },
      },
      () => {
        setRunning(false);
        message.error('SSE 连接中断，评测 API 可能尚未就绪');
        sseRef.current?.close();
      },
    );

    sseRef.current = source;
  }, [selectedDataset]);

  const progressPercent = progress
    ? Math.round((progress.current / progress.total) * 100)
    : 0;

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate('/benchmark')}
        >
          返回列表
        </Button>
      </Space>
      <Title level={3}>运行评测</Title>

      <Card style={{ maxWidth: 600 }}>
        <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <Text strong>选择数据集</Text>
            <Select
              style={{ width: '100%', marginTop: 8 }}
              value={selectedDataset}
              onChange={setSelectedDataset}
              disabled={running}
              options={datasets.map((ds) => ({ label: ds, value: ds }))}
              placeholder="选择评测数据集"
            />
          </div>

          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={running}
            onClick={handleRun}
            block
          >
            {running ? '评测运行中...' : '开始评测'}
          </Button>

          {(running || completed) && (
            <div>
              <Progress
                percent={completed ? 100 : progressPercent}
                status={completed ? 'success' : 'active'}
              />
              {progress && !completed && (
                <Text type="secondary">
                  正在处理: {progress.case_id} ({progress.current}/{progress.total}) — {progress.stage}
                </Text>
              )}
              {completed && (
                <Button
                  type="link"
                  onClick={() => navigate(`/benchmark/${completedRunId}`)}
                >
                  查看报告详情
                </Button>
              )}
            </div>
          )}
        </Space>
      </Card>
    </div>
  );
}
