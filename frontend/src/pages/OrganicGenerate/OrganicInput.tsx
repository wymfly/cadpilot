import { useState } from 'react';
import { Input, Upload, message, Typography } from 'antd';
import { InboxOutlined, DeleteOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd';

const { TextArea } = Input;
const { Dragger } = Upload;
const { Text } = Typography;

const MAX_SIZE_MB = 10;
const ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

interface OrganicInputProps {
  prompt: string;
  onPromptChange: (value: string) => void;
  imageFile: File | null;
  onImageChange: (file: File | null) => void;
  disabled?: boolean;
}

export default function OrganicInput({
  prompt,
  onPromptChange,
  imageFile,
  onImageChange,
  disabled,
}: OrganicInputProps) {
  const [fileList, setFileList] = useState<UploadFile[]>(() =>
    imageFile
      ? [{ uid: '-1', name: imageFile.name, status: 'done' as const }]
      : [],
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>
          文本描述
        </Text>
        <TextArea
          rows={3}
          placeholder="描述你想要的 3D 模型，例如：一个流线型的花瓶，底部宽顶部窄，带有螺旋纹路装饰"
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
          maxLength={2000}
          showCount
          disabled={disabled}
        />
      </div>

      <div>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>
          参考图片 <Text type="secondary">(可选)</Text>
        </Text>
        <Dragger
          accept=".png,.jpg,.jpeg,.webp"
          maxCount={1}
          fileList={fileList}
          disabled={disabled}
          beforeUpload={(file) => {
            if (!ACCEPTED_TYPES.includes(file.type)) {
              message.error('仅支持 PNG、JPEG、WebP 格式');
              return Upload.LIST_IGNORE;
            }
            if (file.size / 1024 / 1024 > MAX_SIZE_MB) {
              message.error(`文件大小不能超过 ${MAX_SIZE_MB}MB`);
              return Upload.LIST_IGNORE;
            }
            onImageChange(file);
            setFileList([
              { uid: '-1', name: file.name, status: 'done', originFileObj: file },
            ]);
            return false;
          }}
          onRemove={() => {
            onImageChange(null);
            setFileList([]);
          }}
          style={{ padding: '8px 0' }}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽上传参考图片</p>
          <p className="ant-upload-hint">
            支持 PNG、JPEG、WebP，最大 {MAX_SIZE_MB}MB
          </p>
        </Dragger>
      </div>
    </div>
  );
}
