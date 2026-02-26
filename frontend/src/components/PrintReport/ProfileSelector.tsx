import { Radio } from 'antd';
import type { ProfileKey } from '../../types/printability.ts';
import { PROFILE_LABELS } from '../../types/printability.ts';

interface ProfileSelectorProps {
  value: ProfileKey;
  onChange: (key: ProfileKey) => void;
}

const PROFILE_KEYS: ProfileKey[] = ['fdm_standard', 'sla_standard', 'sls_standard'];

export default function ProfileSelector({ value, onChange }: ProfileSelectorProps) {
  return (
    <Radio.Group
      value={value}
      onChange={(e) => onChange(e.target.value as ProfileKey)}
      optionType="button"
      buttonStyle="solid"
      size="small"
      options={PROFILE_KEYS.map((key) => ({
        label: PROFILE_LABELS[key].label,
        value: key,
      }))}
    />
  );
}
