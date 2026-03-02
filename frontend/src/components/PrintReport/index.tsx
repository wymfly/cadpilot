import { useState, useMemo } from 'react';
import { Card, Descriptions, Tag, Space, Statistic, Row, Col } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  PrinterOutlined,
  DollarOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import ProfileSelector from './ProfileSelector.tsx';
import IssueList from './IssueList.tsx';
import type { PrintabilityResult, ProfileKey } from '../../types/printability.ts';

interface PrintReportProps {
  /** Printability results keyed by profile name, or a single result. */
  results: Record<string, PrintabilityResult> | PrintabilityResult;
  defaultProfile?: ProfileKey;
  onLocateIssue?: (region: { center: number[]; radius: number }) => void;
}

export default function PrintReport({
  results,
  defaultProfile = 'fdm_standard',
  onLocateIssue,
}: PrintReportProps) {
  const [selectedProfile, setSelectedProfile] = useState<ProfileKey>(defaultProfile);

  const isMulti = useMemo(
    () => !('printable' in results),
    [results],
  );

  const currentResult: PrintabilityResult | undefined = useMemo(() => {
    if (!isMulti) return results as PrintabilityResult;
    return (results as Record<string, PrintabilityResult>)[selectedProfile];
  }, [results, isMulti, selectedProfile]);

  if (!currentResult) {
    return (
      <Card size="small" title="可打印性报告">
        <div style={{ textAlign: 'center', padding: 24, color: '#999' }}>
          暂无检查结果
        </div>
      </Card>
    );
  }

  const errorCount = currentResult.issues.filter((i) => i.severity === 'error').length;
  const warnCount = currentResult.issues.filter((i) => i.severity === 'warning').length;

  return (
    <Card
      size="small"
      title={
        <Space>
          <PrinterOutlined />
          可打印性报告
        </Space>
      }
      extra={
        currentResult.printable ? (
          <Tag icon={<CheckCircleOutlined />} color="success">
            可打印
          </Tag>
        ) : (
          <Tag icon={<CloseCircleOutlined />} color="error">
            不可打印
          </Tag>
        )
      }
    >
      {isMulti && (
        <div style={{ marginBottom: 12 }}>
          <ProfileSelector value={selectedProfile} onChange={setSelectedProfile} />
        </div>
      )}

      <Row gutter={16} style={{ marginBottom: 12 }}>
        {currentResult.material_volume_cm3 != null && (
          <Col span={8}>
            <Statistic
              title="材料体积"
              value={currentResult.material_volume_cm3}
              precision={2}
              suffix="cm³"
              valueStyle={{ fontSize: 16 }}
            />
          </Col>
        )}
        {currentResult.bounding_box && (
          <Col span={16}>
            <Statistic
              title="包围盒 (mm)"
              value={`${currentResult.bounding_box.x} × ${currentResult.bounding_box.y} × ${currentResult.bounding_box.z}`}
              valueStyle={{ fontSize: 16 }}
            />
          </Col>
        )}
      </Row>

      {/* Material estimate */}
      {currentResult.material_estimate && (
        <Row gutter={16} style={{ marginBottom: 12 }}>
          <Col span={8}>
            <Statistic
              title="耗材重量"
              value={currentResult.material_estimate.filament_weight_g}
              precision={1}
              suffix="g"
              prefix={<DollarOutlined />}
              valueStyle={{ fontSize: 16 }}
            />
          </Col>
          <Col span={8}>
            <Statistic
              title="耗材长度"
              value={currentResult.material_estimate.filament_length_m}
              precision={2}
              suffix="m"
              valueStyle={{ fontSize: 16 }}
            />
          </Col>
          <Col span={8}>
            <Statistic
              title="预估费用"
              value={currentResult.material_estimate.cost_estimate_cny}
              precision={2}
              prefix="¥"
              valueStyle={{ fontSize: 16 }}
            />
          </Col>
        </Row>
      )}

      {/* Time estimate */}
      {currentResult.time_estimate && (
        <Row gutter={16} style={{ marginBottom: 12 }}>
          <Col span={12}>
            <Statistic
              title="预估打印时间"
              value={currentResult.time_estimate.total_minutes}
              suffix="分钟"
              prefix={<ClockCircleOutlined />}
              valueStyle={{ fontSize: 16 }}
            />
          </Col>
          <Col span={12}>
            <Statistic
              title="层数"
              value={currentResult.time_estimate.layer_count}
              suffix="层"
              valueStyle={{ fontSize: 16 }}
            />
          </Col>
        </Row>
      )}

      {(errorCount > 0 || warnCount > 0) && (
        <Descriptions size="small" column={3} style={{ marginBottom: 8 }}>
          <Descriptions.Item label="错误">
            <span style={{ color: errorCount > 0 ? '#ff4d4f' : '#52c41a' }}>
              {errorCount}
            </span>
          </Descriptions.Item>
          <Descriptions.Item label="警告">
            <span style={{ color: warnCount > 0 ? '#faad14' : '#52c41a' }}>
              {warnCount}
            </span>
          </Descriptions.Item>
          <Descriptions.Item label="配置">
            {currentResult.profile}
          </Descriptions.Item>
        </Descriptions>
      )}

      <IssueList issues={currentResult.issues} onLocateIssue={onLocateIssue} />
    </Card>
  );
}
