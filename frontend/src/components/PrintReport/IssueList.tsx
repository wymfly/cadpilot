import { List, Tag, Typography, Button, Tooltip } from 'antd';
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  CloseCircleOutlined,
  AimOutlined,
} from '@ant-design/icons';
import type { PrintIssue } from '../../types/printability.ts';

const { Text } = Typography;

const SEVERITY_CONFIG = {
  error: { color: 'error', icon: <CloseCircleOutlined />, label: '错误' },
  warning: { color: 'warning', icon: <ExclamationCircleOutlined />, label: '警告' },
  info: { color: 'processing', icon: <CheckCircleOutlined />, label: '提示' },
} as const;

const CHECK_LABELS: Record<string, string> = {
  wall_thickness: '壁厚',
  overhang: '悬挑角',
  hole_diameter: '孔径',
  rib_thickness: '筋厚',
  build_volume: '构建体积',
};

interface IssueListProps {
  issues: PrintIssue[];
  onLocateIssue?: (region: { center: number[]; radius: number }) => void;
}

export default function IssueList({ issues, onLocateIssue }: IssueListProps) {
  if (issues.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '12px 0', color: '#52c41a' }}>
        <CheckCircleOutlined style={{ fontSize: 20, marginRight: 8 }} />
        所有检查项通过
      </div>
    );
  }

  return (
    <List
      size="small"
      dataSource={issues}
      renderItem={(issue) => {
        const cfg = SEVERITY_CONFIG[issue.severity] ?? SEVERITY_CONFIG.info;
        return (
          <List.Item
            extra={
              issue.region && onLocateIssue ? (
                <Tooltip title="在 3D 视图中定位">
                  <Button
                    type="text"
                    size="small"
                    icon={<AimOutlined />}
                    onClick={() => onLocateIssue(issue.region!)}
                  />
                </Tooltip>
              ) : undefined
            }
          >
            <List.Item.Meta
              avatar={cfg.icon}
              title={
                <span>
                  <Tag color={cfg.color}>{cfg.label}</Tag>
                  {CHECK_LABELS[issue.check] ?? issue.check}
                </span>
              }
              description={
                <>
                  <div>{issue.message}</div>
                  {issue.suggestion && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      建议: {issue.suggestion}
                    </Text>
                  )}
                </>
              }
            />
          </List.Item>
        );
      }}
    />
  );
}
