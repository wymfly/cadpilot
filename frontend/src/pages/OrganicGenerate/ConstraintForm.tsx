import { Button, InputNumber, Select, Space, Typography, Divider } from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import type { OrganicConstraints, EngineeringCut, CutType, CutDirection } from '../../types/organic.ts';

const { Text } = Typography;

const CUT_TYPE_OPTIONS: { label: string; value: CutType }[] = [
  { label: '平底切割', value: 'flat_bottom' },
  { label: '圆孔', value: 'hole' },
  { label: '矩形槽', value: 'slot' },
];

const DIRECTION_OPTIONS: { label: string; value: CutDirection }[] = [
  { label: '顶部', value: 'top' },
  { label: '底部', value: 'bottom' },
  { label: '前方', value: 'front' },
  { label: '后方', value: 'back' },
  { label: '左侧', value: 'left' },
  { label: '右侧', value: 'right' },
];

interface ConstraintFormProps {
  constraints: OrganicConstraints;
  onChange: (constraints: OrganicConstraints) => void;
  disabled?: boolean;
}

export default function ConstraintForm({ constraints, onChange, disabled }: ConstraintFormProps) {
  const updateBBox = (index: number, value: number | null) => {
    if (value === null) {
      if (constraints.bounding_box) {
        const allNull = constraints.bounding_box.every((v, i) => (i === index ? true : v === 0));
        if (allNull) {
          onChange({ ...constraints, bounding_box: null });
          return;
        }
      }
      return;
    }
    const bbox: [number, number, number] = constraints.bounding_box
      ? [...constraints.bounding_box]
      : [0, 0, 0];
    bbox[index] = value;
    onChange({ ...constraints, bounding_box: bbox });
  };

  const addCut = () => {
    const newCut: EngineeringCut = { type: 'flat_bottom', offset: 0 };
    onChange({ ...constraints, engineering_cuts: [...constraints.engineering_cuts, newCut] });
  };

  const removeCut = (index: number) => {
    const cuts = constraints.engineering_cuts.filter((_, i) => i !== index);
    onChange({ ...constraints, engineering_cuts: cuts });
  };

  const updateCut = (index: number, updates: Partial<EngineeringCut>) => {
    const cuts = constraints.engineering_cuts.map((cut, i) =>
      i === index ? { ...cut, ...updates } : cut,
    );
    onChange({ ...constraints, engineering_cuts: cuts });
  };

  return (
    <div>
      <Text strong>包围盒尺寸 (mm)</Text>
      <div style={{ display: 'flex', gap: 8, marginTop: 8, marginBottom: 16 }}>
        <InputNumber
          placeholder="X"
          min={1}
          max={1000}
          value={constraints.bounding_box?.[0] ?? undefined}
          onChange={(v) => updateBBox(0, v)}
          disabled={disabled}
          style={{ flex: 1 }}
          addonAfter="X"
        />
        <InputNumber
          placeholder="Y"
          min={1}
          max={1000}
          value={constraints.bounding_box?.[1] ?? undefined}
          onChange={(v) => updateBBox(1, v)}
          disabled={disabled}
          style={{ flex: 1 }}
          addonAfter="Y"
        />
        <InputNumber
          placeholder="Z"
          min={1}
          max={1000}
          value={constraints.bounding_box?.[2] ?? undefined}
          onChange={(v) => updateBBox(2, v)}
          disabled={disabled}
          style={{ flex: 1 }}
          addonAfter="Z"
        />
      </div>

      <Divider style={{ margin: '12px 0' }} />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <Text strong>工程切割接口</Text>
        <Button
          type="dashed"
          size="small"
          icon={<PlusOutlined />}
          onClick={addCut}
          disabled={disabled}
        >
          添加
        </Button>
      </div>

      {constraints.engineering_cuts.map((cut, index) => (
        <div
          key={index}
          style={{
            border: '1px solid #f0f0f0',
            borderRadius: 6,
            padding: 12,
            marginBottom: 8,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <Select
              value={cut.type}
              options={CUT_TYPE_OPTIONS}
              onChange={(type: CutType) => {
                const base: EngineeringCut = { type };
                if (type === 'flat_bottom') base.offset = 0;
                if (type === 'hole') {
                  base.diameter = 5;
                  base.depth = 10;
                  base.direction = 'bottom';
                }
                if (type === 'slot') {
                  base.width = 10;
                  base.depth = 5;
                  base.length = 20;
                  base.direction = 'bottom';
                }
                updateCut(index, base);
              }}
              disabled={disabled}
              style={{ width: 120 }}
            />
            <Button
              type="text"
              danger
              icon={<DeleteOutlined />}
              onClick={() => removeCut(index)}
              disabled={disabled}
            />
          </div>

          {cut.type === 'flat_bottom' && (
            <Space>
              <Text type="secondary">偏移:</Text>
              <InputNumber
                min={0}
                max={100}
                value={cut.offset}
                onChange={(v) => updateCut(index, { offset: v ?? 0 })}
                disabled={disabled}
                addonAfter="mm"
                size="small"
              />
            </Space>
          )}

          {cut.type === 'hole' && (
            <Space wrap>
              <InputNumber
                min={0.1}
                max={200}
                value={cut.diameter}
                onChange={(v) => updateCut(index, { diameter: v ?? undefined })}
                disabled={disabled}
                addonBefore="直径"
                addonAfter="mm"
                size="small"
              />
              <InputNumber
                min={0.1}
                max={500}
                value={cut.depth}
                onChange={(v) => updateCut(index, { depth: v ?? undefined })}
                disabled={disabled}
                addonBefore="深度"
                addonAfter="mm"
                size="small"
              />
              <Select
                value={cut.direction ?? 'bottom'}
                options={DIRECTION_OPTIONS}
                onChange={(d: CutDirection) => updateCut(index, { direction: d })}
                disabled={disabled}
                size="small"
                style={{ width: 90 }}
              />
            </Space>
          )}

          {cut.type === 'slot' && (
            <Space wrap>
              <InputNumber
                min={0.1}
                max={200}
                value={cut.width}
                onChange={(v) => updateCut(index, { width: v ?? undefined })}
                disabled={disabled}
                addonBefore="宽"
                addonAfter="mm"
                size="small"
              />
              <InputNumber
                min={0.1}
                max={500}
                value={cut.depth}
                onChange={(v) => updateCut(index, { depth: v ?? undefined })}
                disabled={disabled}
                addonBefore="深"
                addonAfter="mm"
                size="small"
              />
              <InputNumber
                min={0.1}
                max={500}
                value={cut.length}
                onChange={(v) => updateCut(index, { length: v ?? undefined })}
                disabled={disabled}
                addonBefore="长"
                addonAfter="mm"
                size="small"
              />
              <Select
                value={cut.direction ?? 'bottom'}
                options={DIRECTION_OPTIONS}
                onChange={(d: CutDirection) => updateCut(index, { direction: d })}
                disabled={disabled}
                size="small"
                style={{ width: 90 }}
              />
            </Space>
          )}
        </div>
      ))}
    </div>
  );
}
