import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Row,
  Col,
  Input,
  Select,
  Typography,
  Empty,
  Spin,
  Pagination,
  message,
} from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useNavigate, useOutletContext } from 'react-router-dom';
import type { WorkbenchOutletContext } from '../../layouts/WorkbenchLayout.tsx';
import { listJobs, type PaginatedJobsResponse } from '../../services/api.ts';
import JobCard from '../../components/JobCard/index.tsx';

const { Title, Text } = Typography;

const PAGE_SIZE = 20;

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

export default function LibraryPage() {
  const { setPanels } = useOutletContext<WorkbenchOutletContext>();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<PaginatedJobsResponse | null>(null);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [keyword, setKeyword] = useState('');

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listJobs({
        page,
        page_size: PAGE_SIZE,
        status: statusFilter || undefined,
        input_type: typeFilter || undefined,
      });
      setData(result);
    } catch {
      message.error('加载零件库失败');
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, typeFilter]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  // Client-side keyword filter (backend may not support keyword search yet)
  const filteredItems = useMemo(() => {
    if (!data) return [];
    if (!keyword.trim()) return data.items;
    const q = keyword.trim().toLowerCase();
    return data.items.filter((item) =>
      (item.input_text ?? '').toLowerCase().includes(q),
    );
  }, [data, keyword]);

  // Left panel: search + filters
  const leftPanel = useMemo(
    () => (
      <div>
        <Title level={5} style={{ marginBottom: 12 }}>
          搜索与筛选
        </Title>

        <div style={{ marginBottom: 12 }}>
          <Text
            strong
            style={{ display: 'block', marginBottom: 4, fontSize: 12 }}
          >
            关键词搜索
          </Text>
          <Input
            placeholder="搜索零件名称..."
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            allowClear
            size="small"
          />
        </div>

        <div style={{ marginBottom: 12 }}>
          <Text
            strong
            style={{ display: 'block', marginBottom: 4, fontSize: 12 }}
          >
            状态
          </Text>
          <Select
            value={statusFilter}
            onChange={(v) => {
              setStatusFilter(v);
              setPage(1);
            }}
            options={STATUS_FILTER_OPTIONS}
            style={{ width: '100%' }}
            size="small"
          />
        </div>

        <div style={{ marginBottom: 12 }}>
          <Text
            strong
            style={{ display: 'block', marginBottom: 4, fontSize: 12 }}
          >
            输入类型
          </Text>
          <Select
            value={typeFilter}
            onChange={(v) => {
              setTypeFilter(v);
              setPage(1);
            }}
            options={TYPE_FILTER_OPTIONS}
            style={{ width: '100%' }}
            size="small"
          />
        </div>

        {data && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            共 {data.total} 条记录
            {keyword.trim() ? `，筛选后 ${filteredItems.length} 条` : ''}
          </Text>
        )}
      </div>
    ),
    [keyword, statusFilter, typeFilter, data, filteredItems.length],
  );

  // Right panel: help text
  const rightPanel = useMemo(
    () => (
      <div>
        <Title level={5}>零件库</Title>
        <Text type="secondary" style={{ fontSize: 13 }}>
          浏览历史生成的 3D 模型。点击任意卡片查看详情、下载或重新生成。
        </Text>
        <div style={{ marginTop: 16 }}>
          <Title level={5}>提示</Title>
          <ul style={{ paddingLeft: 16, color: '#666', fontSize: 13 }}>
            <li>使用左侧筛选器缩小范围</li>
            <li>点击卡片进入详情页</li>
            <li>已完成的模型可下载 STEP/STL/3MF</li>
            <li>支持基于历史参数重新生成</li>
          </ul>
        </div>
      </div>
    ),
    [],
  );

  useEffect(() => {
    setPanels({ left: leftPanel, right: rightPanel });
  }, [leftPanel, rightPanel, setPanels]);

  // Center: card grid
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        overflow: 'auto',
        padding: 16,
      }}
    >
      <Spin spinning={loading}>
        {filteredItems.length > 0 ? (
          <>
            <Row gutter={[16, 16]}>
              {filteredItems.map((job) => (
                <Col key={job.job_id} xs={24} sm={12} md={8} xl={6}>
                  <JobCard
                    job={job}
                    onClick={() => navigate(`/library/${job.job_id}`)}
                  />
                </Col>
              ))}
            </Row>

            {data && data.total > PAGE_SIZE && (
              <div style={{ textAlign: 'center', marginTop: 24 }}>
                <Pagination
                  current={page}
                  total={data.total}
                  pageSize={PAGE_SIZE}
                  onChange={setPage}
                  showSizeChanger={false}
                />
              </div>
            )}
          </>
        ) : (
          !loading && (
            <Empty
              description={keyword.trim() ? '未找到匹配的零件' : '暂无生成记录'}
              style={{ marginTop: 80 }}
            />
          )
        )}
      </Spin>
    </div>
  );
}
