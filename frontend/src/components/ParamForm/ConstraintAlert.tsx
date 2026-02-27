import { Alert, Space } from 'antd';
import type { ConstraintViolation } from '../../types/standard.ts';

interface ConstraintAlertProps {
  violations: ConstraintViolation[];
}

export default function ConstraintAlert({ violations }: ConstraintAlertProps) {
  if (violations.length === 0) return null;

  return (
    <Space orientation="vertical" size={8} style={{ width: '100%', marginBottom: 16 }}>
      {violations.map((v, i) => (
        <Alert
          key={i}
          type={v.severity === 'error' ? 'error' : 'warning'}
          message={v.message}
          description={v.constraint}
          showIcon
          closable={false}
        />
      ))}
    </Space>
  );
}
