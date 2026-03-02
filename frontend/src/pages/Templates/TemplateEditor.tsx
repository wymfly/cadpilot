import { useState, useEffect } from 'react';
import {
  Typography,
  Form,
  Input,
  Select,
  Button,
  Space,
  Spin,
  Card,
  message,
} from 'antd';
import { ArrowLeftOutlined, SaveOutlined } from '@ant-design/icons';
import { getTemplate, createTemplate, updateTemplate } from '../../services/api.ts';
import type { ParametricTemplate } from '../../types/template.ts';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';

const { Title } = Typography;
const { TextArea } = Input;

const PART_TYPE_OPTIONS = [
  { label: '回转体', value: 'rotational' },
  { label: '阶梯回转体', value: 'rotational_stepped' },
  { label: '板件', value: 'plate' },
  { label: '支架', value: 'bracket' },
  { label: '壳体', value: 'housing' },
  { label: '齿轮', value: 'gear' },
  { label: '通用', value: 'general' },
];

interface TemplateEditorProps {
  name?: string;
  onBack: () => void;
  onSave: () => void;
}

export default function TemplateEditor({
  name,
  onBack,
  onSave,
}: TemplateEditorProps) {
  const dt = useDesignTokens();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const isEdit = !!name;

  useEffect(() => {
    if (!name) return;
    setLoading(true);
    getTemplate(name)
      .then((tpl) => {
        form.setFieldsValue({
          name: tpl.name,
          display_name: tpl.display_name,
          part_type: tpl.part_type,
          description: tpl.description,
          code_template: tpl.code_template,
          constraints: tpl.constraints.join('\n'),
        });
      })
      .catch(() => {
        message.error('加载模板失败');
      })
      .finally(() => setLoading(false));
  }, [name, form]);

  const handleSubmit = async (values: Record<string, string>) => {
    setSaving(true);
    try {
      const payload: Partial<ParametricTemplate> = {
        name: values.name,
        display_name: values.display_name,
        part_type: values.part_type,
        description: values.description,
        code_template: values.code_template,
        constraints: values.constraints
          ? values.constraints
              .split('\n')
              .map((s: string) => s.trim())
              .filter(Boolean)
          : [],
      };

      if (isEdit) {
        await updateTemplate(name, payload);
        message.success('模板已更新');
      } else {
        await createTemplate(payload);
        message.success('模板已创建');
      }
      onSave();
    } catch {
      message.error(isEdit ? '更新失败' : '创建失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={onBack}>
          返回
        </Button>
        <Title level={3} style={{ margin: 0 }}>
          {isEdit ? '编辑模板' : '新建模板'}
        </Title>
      </Space>

      <Card>
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          style={{ maxWidth: 800 }}
        >
          <Form.Item
            label="模板名称"
            name="name"
            rules={[
              { required: true, message: '请输入模板名称' },
              {
                pattern: /^[a-z][a-z0-9_]*$/,
                message: '仅允许小写字母、数字和下划线，以字母开头',
              },
            ]}
          >
            <Input
              placeholder="例如: flanged_cylinder"
              disabled={isEdit}
            />
          </Form.Item>

          <Form.Item
            label="显示名称"
            name="display_name"
            rules={[{ required: true, message: '请输入显示名称' }]}
          >
            <Input placeholder="例如: 带法兰圆柱体" />
          </Form.Item>

          <Form.Item
            label="零件类型"
            name="part_type"
            rules={[{ required: true, message: '请选择零件类型' }]}
          >
            <Select options={PART_TYPE_OPTIONS} placeholder="选择零件类型" />
          </Form.Item>

          <Form.Item
            label="描述"
            name="description"
            rules={[{ required: true, message: '请输入描述' }]}
          >
            <TextArea rows={3} placeholder="模板功能描述" />
          </Form.Item>

          <Form.Item
            label="约束条件"
            name="constraints"
            tooltip="每行一个约束表达式，例如: diameter > 0"
          >
            <TextArea
              rows={4}
              placeholder="每行一个约束表达式"
              style={{ fontFamily: dt.typography.fontMono }}
            />
          </Form.Item>

          <Form.Item
            label="代码模板"
            name="code_template"
            rules={[{ required: true, message: '请输入代码模板' }]}
          >
            <TextArea
              rows={20}
              placeholder="CadQuery 代码模板，使用 {{param_name}} 作为参数占位符"
              style={{ fontFamily: 'monospace', fontSize: 13 }}
            />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button
                type="primary"
                htmlType="submit"
                icon={<SaveOutlined />}
                loading={saving}
              >
                {isEdit ? '保存修改' : '创建模板'}
              </Button>
              <Button onClick={onBack}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
