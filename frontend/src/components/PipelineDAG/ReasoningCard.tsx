import { Collapse, Empty, Typography } from 'antd';

const { Text } = Typography;

interface ReasoningCardProps {
  reasoning: Record<string, string> | null;
}

const LABEL_MAP: Record<string, string> = {
  part_type: '零件类型识别',
  part_type_detection: '零件类型识别',
  template_match: '模板匹配',
  template_selection: '模板选择',
  candidate_count: '候选模板数',
  recommendations: '工程标准建议',
  method: '生成方法',
  template: '使用模板',
  pipeline: '生成管道',
  printable: '可打印性',
  issues_count: '问题数量',
  recommendations_count: '建议数量',
  input_routing: '输入路由',
  confirmation: '确认状态',
  final_status: '最终状态',
  spec_source: '分析来源',
  format: '输出格式',
  result: '转换结果',
};

export default function ReasoningCard({ reasoning }: ReasoningCardProps) {
  if (!reasoning || Object.keys(reasoning).length === 0) {
    return <Empty description="无推理数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  const items = Object.entries(reasoning).map(([key, value]) => ({
    key,
    label: LABEL_MAP[key] || key,
    children: <Text>{value}</Text>,
  }));

  return (
    <Collapse
      size="small"
      defaultActiveKey={items.map((i) => i.key)}
      items={items}
    />
  );
}
