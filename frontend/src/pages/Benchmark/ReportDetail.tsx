import { useState, useEffect, useMemo } from 'react';
import {
  Typography,
  Card,
  Row,
  Col,
  Statistic,
  Table,
  Tag,
  Button,
  Space,
  Spin,
  message,
} from 'antd';
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';
import { getBenchmarkReport } from '../../services/api.ts';
import type { BenchmarkReport, CaseResult, FailureCategory } from '../../types/benchmark.ts';
import { useDesignTokens, type ResolvedColors } from '../../theme/useDesignTokens.ts';

const { Title, Text } = Typography;

const FAILURE_LABELS: Record<FailureCategory, string> = {
  TYPE_RECOGNITION: '类型识别',
  ANNOTATION_MISS: '标注遗漏',
  CODE_EXECUTION: '代码执行',
  STRUCTURAL_ERROR: '结构错误',
  DIMENSION_DEVIATION: '尺寸偏差',
};

const FAILURE_COLORS: Record<FailureCategory, string> = {
  TYPE_RECOGNITION: 'magenta',
  ANNOTATION_MISS: 'orange',
  CODE_EXECUTION: 'red',
  STRUCTURAL_ERROR: 'volcano',
  DIMENSION_DEVIATION: 'gold',
};

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function getCaseColumns(c: ResolvedColors): ColumnsType<CaseResult> {
  return [
    {
      title: 'Case',
      dataIndex: 'case_id',
      key: 'case_id',
      width: 100,
    },
    {
      title: '编译',
      dataIndex: 'compiled',
      key: 'compiled',
      width: 70,
      render: (val: boolean) =>
        val ? (
          <CheckCircleOutlined style={{ color: c.success }} />
        ) : (
          <CloseCircleOutlined style={{ color: c.error }} />
        ),
    },
    {
      title: '类型正确',
      dataIndex: 'type_correct',
      key: 'type_correct',
      width: 90,
      render: (val: boolean) =>
        val ? (
          <CheckCircleOutlined style={{ color: c.success }} />
        ) : (
          <CloseCircleOutlined style={{ color: c.error }} />
        ),
    },
    {
      title: '参数准确率',
      dataIndex: 'param_accuracy',
      key: 'param_accuracy',
      width: 100,
      render: (val: number) => formatPercent(val),
    },
    {
      title: '几何匹配',
      dataIndex: 'bbox_match',
      key: 'bbox_match',
      width: 90,
      render: (val: boolean) =>
        val ? (
          <CheckCircleOutlined style={{ color: c.success }} />
        ) : (
          <CloseCircleOutlined style={{ color: c.error }} />
        ),
    },
    {
      title: '耗时',
      dataIndex: 'duration_s',
      key: 'duration_s',
      width: 80,
      render: (val: number) => `${val.toFixed(1)}s`,
    },
    {
      title: '失败分类',
      dataIndex: 'failure_category',
      key: 'failure_category',
      width: 110,
      render: (val?: FailureCategory) =>
        val ? (
          <Tag color={FAILURE_COLORS[val]}>{FAILURE_LABELS[val]}</Tag>
        ) : (
          <Tag color="green">通过</Tag>
        ),
    },
  ];
}

export default function ReportDetail() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const dt = useDesignTokens();
  const caseColumns = useMemo(() => getCaseColumns(dt.color), [dt.color]);
  const [report, setReport] = useState<BenchmarkReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!runId) return;
    setLoading(true);
    getBenchmarkReport(runId)
      .then(setReport)
      .catch(() => {
        message.error('无法加载报告，评测 API 可能尚未就绪');
      })
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!report) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Text type="secondary">报告不存在或加载失败</Text>
        <br />
        <Button
          style={{ marginTop: 16 }}
          onClick={() => navigate('/benchmark')}
        >
          返回列表
        </Button>
      </div>
    );
  }

  const { metrics, failure_counts, results } = report;

  const failureSorted = Object.entries(failure_counts)
    .filter(([, count]) => count > 0)
    .sort(([, a], [, b]) => b - a) as [FailureCategory, number][];

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

      <Title level={3}>
        评测报告 — {report.dataset}
      </Title>
      <Text type="secondary">
        {new Date(report.timestamp).toLocaleString('zh-CN')} | ID: {report.run_id}
      </Text>

      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small">
            <Statistic
              title="编译率"
              value={metrics.compile_rate * 100}
              precision={1}
              suffix="%"
              valueStyle={{
                color: metrics.compile_rate >= 0.8 ? dt.color.success : dt.color.error,
              }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small">
            <Statistic
              title="类型准确率"
              value={metrics.type_accuracy * 100}
              precision={1}
              suffix="%"
              valueStyle={{
                color: metrics.type_accuracy >= 0.8 ? dt.color.success : dt.color.error,
              }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small">
            <Statistic
              title="参数准确率 (P50)"
              value={metrics.param_accuracy_p50 * 100}
              precision={1}
              suffix="%"
              valueStyle={{
                color: metrics.param_accuracy_p50 >= 0.8 ? dt.color.success : dt.color.error,
              }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small">
            <Statistic
              title="几何匹配率"
              value={metrics.bbox_match_rate * 100}
              precision={1}
              suffix="%"
              valueStyle={{
                color: metrics.bbox_match_rate >= 0.8 ? dt.color.success : dt.color.error,
              }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small">
            <Statistic
              title="平均耗时"
              value={metrics.avg_duration_s}
              precision={1}
              suffix="s"
            />
          </Card>
        </Col>
      </Row>

      {failureSorted.length > 0 && (
        <Card
          size="small"
          title="失败分类统计"
          style={{ marginTop: 16 }}
        >
          <Row gutter={[12, 8]}>
            {failureSorted.map(([category, count]) => (
              <Col key={category}>
                <Tag color={FAILURE_COLORS[category]}>
                  {FAILURE_LABELS[category]}: {count}
                </Tag>
              </Col>
            ))}
          </Row>
          <div style={{ marginTop: 12 }}>
            {failureSorted.map(([category, count]) => {
              const maxCount = failureSorted[0][1];
              const widthPercent = (count / maxCount) * 100;
              return (
                <div
                  key={category}
                  style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}
                >
                  <Text
                    style={{ width: 80, fontSize: 12, flexShrink: 0 }}
                  >
                    {FAILURE_LABELS[category]}
                  </Text>
                  <div
                    style={{
                      height: 16,
                      width: `${widthPercent}%`,
                      minWidth: 20,
                      maxWidth: '60%',
                      background: FAILURE_COLORS[category] === 'red' ? dt.color.error
                        : FAILURE_COLORS[category] === 'orange' ? dt.color.warning
                        : FAILURE_COLORS[category] === 'magenta' ? dt.color.error
                        : FAILURE_COLORS[category] === 'volcano' ? dt.color.error
                        : dt.color.warning,
                      borderRadius: 2,
                      marginRight: 8,
                    }}
                  />
                  <Text style={{ fontSize: 12 }}>{count}</Text>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      <Card
        size="small"
        title="逐 Case 结果"
        style={{ marginTop: 16 }}
      >
        <Table<CaseResult>
          columns={caseColumns}
          dataSource={results}
          rowKey="case_id"
          pagination={false}
          size="small"
          expandable={{
            expandedRowRender: (record) => (
              <div style={{ padding: '8px 0' }}>
                {record.error_detail && (
                  <div>
                    <Text type="danger" strong>错误信息: </Text>
                    <Text code>{record.error_detail}</Text>
                  </div>
                )}
                {!record.error_detail && (
                  <Text type="secondary">无错误信息</Text>
                )}
              </div>
            ),
          }}
        />
      </Card>
    </div>
  );
}
