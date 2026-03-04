import { Switch, Slider, InputNumber, Select, Input, Typography, Divider } from 'antd';

const { Text } = Typography;

interface JsonSchemaProperty {
  type?: string;
  description?: string;
  minimum?: number;
  maximum?: number;
  enum?: string[];
  default?: unknown;
  'x-sensitive'?: boolean;
  'x-group'?: string;
}

interface SchemaFormProps {
  schema: {
    properties?: Record<string, JsonSchemaProperty>;
    [key: string]: unknown;
  };
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
}

/** Fields handled by NodeConfigCard header — skip in SchemaForm */
const SKIP_FIELDS = new Set(['enabled', 'strategy']);

function renderField(
  name: string,
  prop: JsonSchemaProperty,
  value: unknown,
  onChange: (val: unknown) => void,
) {
  // Sensitive → Password
  if (prop['x-sensitive']) {
    return (
      <Input.Password
        value={(value as string) ?? (prop.default as string) ?? ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder={prop.description}
        size="small"
      />
    );
  }

  // Boolean → Switch
  if (prop.type === 'boolean') {
    return (
      <Switch
        size="small"
        checked={(value as boolean) ?? (prop.default as boolean) ?? false}
        onChange={onChange}
      />
    );
  }

  // Integer/Number with min+max → Slider
  if ((prop.type === 'integer' || prop.type === 'number') &&
      prop.minimum != null && prop.maximum != null) {
    return (
      <Slider
        min={prop.minimum}
        max={prop.maximum}
        step={prop.type === 'number' ? (prop.maximum! - prop.minimum!) / 100 : 1}
        value={(value as number) ?? (prop.default as number) ?? prop.minimum}
        onChange={onChange}
      />
    );
  }

  // Integer/Number without range → InputNumber
  if (prop.type === 'integer' || prop.type === 'number') {
    return (
      <InputNumber
        size="small"
        value={(value as number) ?? (prop.default as number)}
        onChange={(val) => onChange(val)}
        min={prop.minimum}
        max={prop.maximum}
        style={{ width: '100%' }}
      />
    );
  }

  // String with enum → Select
  if (prop.type === 'string' && prop.enum) {
    return (
      <Select
        size="small"
        value={(value as string) ?? (prop.default as string) ?? prop.enum[0]}
        onChange={onChange}
        options={prop.enum.map((e) => ({ label: e, value: e }))}
        style={{ width: '100%' }}
      />
    );
  }

  // String without enum → Input
  if (prop.type === 'string') {
    return (
      <Input
        size="small"
        value={(value as string) ?? (prop.default as string) ?? ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder={prop.description}
      />
    );
  }

  // Unsupported (object, array, etc.) → read-only JSON
  return (
    <Text type="secondary" code style={{ fontSize: 12 }}>
      {JSON.stringify(value ?? prop.default ?? null)}
    </Text>
  );
}

export default function SchemaForm({ schema, value, onChange }: SchemaFormProps) {
  const properties = schema.properties ?? {};
  const requiredFields = new Set((schema.required as string[] | undefined) ?? []);

  // Filter and group
  const fields = Object.entries(properties).filter(([name]) => !SKIP_FIELDS.has(name));

  // Group by x-group
  const groups: Record<string, [string, JsonSchemaProperty][]> = {};
  for (const entry of fields) {
    const group = entry[1]['x-group'] ?? '_default';
    if (!groups[group]) groups[group] = [];
    groups[group].push(entry);
  }

  const handleChange = (fieldName: string, fieldValue: unknown) => {
    onChange({ ...value, [fieldName]: fieldValue });
  };

  if (fields.length === 0) return null;

  return (
    <div style={{ padding: '8px 0' }}>
      {Object.entries(groups).map(([group, groupFields]) => (
        <div key={group}>
          {group !== '_default' && (
            <Divider orientation="left" plain style={{ margin: '8px 0', fontSize: 12 }}>
              {group}
            </Divider>
          )}
          {groupFields.map(([name, prop]) => (
            <div key={name} style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <Text style={{ fontSize: 12, flex: '0 0 auto' }}>
                  {requiredFields.has(name) && <span style={{ color: '#ff4d4f', marginRight: 2 }}>*</span>}
                  {prop.description ?? name}
                </Text>
                <div style={{ flex: 1, maxWidth: 200 }}>
                  {renderField(name, prop, value[name], (v) => handleChange(name, v))}
                </div>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
