import { useState } from 'react';
import { Tabs, Input, Upload, message } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd';

const { TextArea } = Input;
const { Dragger } = Upload;

const MAX_SIZE_MB = 10;
const ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

interface OrganicInputProps {
  prompt: string;
  onPromptChange: (value: string) => void;
  onImageChange: (file: File | null) => void;
  disabled?: boolean;
}

export default function OrganicInput({
  prompt,
  onPromptChange,
  onImageChange,
  disabled,
}: OrganicInputProps) {
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  return (
    <Tabs
      defaultActiveKey="text"
      items={[
        {
          key: 'text',
          label: '文本描述',
          children: (
            <TextArea
              rows={4}
              placeholder="描述你想要的 3D 模型，例如：一个流线型的花瓶，底部宽顶部窄，带有螺旋纹路装饰"
              value={prompt}
              onChange={(e) => onPromptChange(e.target.value)}
              maxLength={2000}
              showCount
              disabled={disabled}
            />
          ),
        },
        {
          key: 'image',
          label: '参考图片',
          children: (
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
                setFileList([{ uid: '-1', name: file.name, status: 'done', originFileObj: file }]);
                return false;
              }}
              onRemove={() => {
                onImageChange(null);
                setFileList([]);
              }}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽上传参考图片</p>
              <p className="ant-upload-hint">
                支持 PNG、JPEG、WebP，最大 {MAX_SIZE_MB}MB
              </p>
            </Dragger>
          ),
        },
      ]}
    />
  );
}
