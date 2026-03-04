import { useState, useEffect, useCallback } from 'react';
import { Collapse, Button, Space, message, Spin, Empty } from 'antd';
import { SaveOutlined, UndoOutlined } from '@ant-design/icons';
import SchemaForm from '../../components/SchemaForm/index.tsx';
import { getSystemConfigSchema, getSystemConfig, updateSystemConfig } from '../../services/api.ts';

/** Convert snake_case to human-readable */
function humanize(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function SystemConfigPanel() {
  const [schemas, setSchemas] = useState<Record<string, { properties: Record<string, unknown> }>>({});
  const [values, setValues] = useState<Record<string, Record<string, unknown>>>({});
  const [savedValues, setSavedValues] = useState<Record<string, Record<string, unknown>>>({});
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [schemaData, configData] = await Promise.all([
        getSystemConfigSchema(),
        getSystemConfig(),
      ]);
      setSchemas(schemaData);
      setValues(configData);
      setSavedValues(configData);
    } catch {
      message.error('加载系统配置失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSave = async () => {
    try {
      await updateSystemConfig(values);
      setSavedValues({ ...values });
      message.success('系统配置已保存');
    } catch {
      message.error('保存失败');
    }
  };

  const handleReset = () => {
    setValues({ ...savedValues });
  };

  const handleNodeChange = (nodeName: string, nodeValues: Record<string, unknown>) => {
    setValues((prev) => ({ ...prev, [nodeName]: nodeValues }));
  };

  if (loading) return <Spin />;

  const nodeNames = Object.keys(schemas);
  if (nodeNames.length === 0) return <Empty description="无系统配置" />;

  const hasChanges = JSON.stringify(values) !== JSON.stringify(savedValues);

  return (
    <div>
      <Collapse
        items={nodeNames.map((nodeName) => ({
          key: nodeName,
          label: humanize(nodeName),
          children: (
            <SchemaForm
              schema={schemas[nodeName] as Record<string, unknown> & { properties?: Record<string, unknown> }}
              value={values[nodeName] ?? {}}
              onChange={(v) => handleNodeChange(nodeName, v)}
              scope="system"
            />
          ),
        }))}
      />
      <Space style={{ marginTop: 16 }}>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          onClick={handleSave}
          disabled={!hasChanges}
        >
          保存
        </Button>
        <Button
          icon={<UndoOutlined />}
          onClick={handleReset}
          disabled={!hasChanges}
        >
          重置
        </Button>
      </Space>
    </div>
  );
}
