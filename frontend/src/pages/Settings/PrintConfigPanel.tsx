import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Tag,
  message,
  Popconfirm,
} from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons';
import type { PrintProfile } from '../../types/printability.ts';
import {
  listPrintProfiles,
  createPrintProfile,
  updatePrintProfile,
  deletePrintProfile,
} from '../../services/api.ts';

interface ProfileRow extends PrintProfile {
  is_preset: boolean;
}

export default function PrintConfigPanel() {
  const [profiles, setProfiles] = useState<ProfileRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [form] = Form.useForm();

  const fetchProfiles = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listPrintProfiles();
      setProfiles(data);
    } catch {
      message.error('加载打印配置失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProfiles();
  }, [fetchProfiles]);

  const handleCreate = () => {
    setEditingName(null);
    form.resetFields();
    setModalOpen(true);
  };

  const handleEdit = (record: ProfileRow) => {
    setEditingName(record.name);
    form.setFieldsValue({
      ...record,
      build_volume_x: record.build_volume[0],
      build_volume_y: record.build_volume[1],
      build_volume_z: record.build_volume[2],
    });
    setModalOpen(true);
  };

  const handleDelete = async (name: string) => {
    try {
      await deletePrintProfile(name);
      message.success('已删除');
      fetchProfiles();
    } catch {
      message.error('删除失败');
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      const body: Record<string, unknown> = {
        name: values.name,
        technology: values.technology,
        min_wall_thickness: values.min_wall_thickness,
        max_overhang_angle: values.max_overhang_angle,
        min_hole_diameter: values.min_hole_diameter,
        min_rib_thickness: values.min_rib_thickness,
        build_volume: [
          values.build_volume_x,
          values.build_volume_y,
          values.build_volume_z,
        ],
      };
      if (editingName) {
        await updatePrintProfile(editingName, body);
        message.success('已更新');
      } else {
        await createPrintProfile(body);
        message.success('已创建');
      }
      setModalOpen(false);
      fetchProfiles();
    } catch {
      message.error('保存失败');
    }
  };

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: ProfileRow) => (
        <Space>
          {name}
          {record.is_preset && <Tag color="blue">预设</Tag>}
        </Space>
      ),
    },
    {
      title: '技术',
      dataIndex: 'technology',
      key: 'technology',
      width: 80,
    },
    {
      title: '最小壁厚',
      dataIndex: 'min_wall_thickness',
      key: 'min_wall_thickness',
      width: 100,
      render: (v: number) => `${v} mm`,
    },
    {
      title: '最大悬挑角',
      dataIndex: 'max_overhang_angle',
      key: 'max_overhang_angle',
      width: 110,
      render: (v: number) => `${v}°`,
    },
    {
      title: '构建体积',
      dataIndex: 'build_volume',
      key: 'build_volume',
      width: 160,
      render: (v: [number, number, number]) => `${v[0]}×${v[1]}×${v[2]} mm`,
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: unknown, record: ProfileRow) =>
        record.is_preset ? (
          <Tag>只读</Tag>
        ) : (
          <Space>
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleEdit(record)}
            />
            <Popconfirm
              title="确定删除此配置？"
              onConfirm={() => handleDelete(record.name)}
            >
              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </Space>
        ),
    },
  ];

  return (
    <Card
      title="打印配置管理"
      size="small"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
          新增配置
        </Button>
      }
    >
      <Table
        rowKey="name"
        columns={columns}
        dataSource={profiles}
        loading={loading}
        pagination={false}
        size="small"
      />
      <Modal
        title={editingName ? '编辑打印配置' : '新增打印配置'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" size="small">
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入配置名称' }]}
          >
            <Input disabled={!!editingName} placeholder="my_fdm_large" />
          </Form.Item>
          <Form.Item
            name="technology"
            label="打印技术"
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { label: 'FDM', value: 'FDM' },
                { label: 'SLA', value: 'SLA' },
                { label: 'SLS', value: 'SLS' },
              ]}
            />
          </Form.Item>
          <Space>
            <Form.Item
              name="min_wall_thickness"
              label="最小壁厚 (mm)"
              rules={[{ required: true }]}
            >
              <InputNumber min={0} step={0.1} />
            </Form.Item>
            <Form.Item
              name="max_overhang_angle"
              label="最大悬挑角 (°)"
              rules={[{ required: true }]}
            >
              <InputNumber min={0} max={90} step={1} />
            </Form.Item>
          </Space>
          <Space>
            <Form.Item
              name="min_hole_diameter"
              label="最小孔径 (mm)"
              rules={[{ required: true }]}
            >
              <InputNumber min={0} step={0.1} />
            </Form.Item>
            <Form.Item
              name="min_rib_thickness"
              label="最小筋厚 (mm)"
              rules={[{ required: true }]}
            >
              <InputNumber min={0} step={0.1} />
            </Form.Item>
          </Space>
          <Space>
            <Form.Item
              name="build_volume_x"
              label="X (mm)"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} step={10} />
            </Form.Item>
            <Form.Item
              name="build_volume_y"
              label="Y (mm)"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} step={10} />
            </Form.Item>
            <Form.Item
              name="build_volume_z"
              label="Z (mm)"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} step={10} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </Card>
  );
}
