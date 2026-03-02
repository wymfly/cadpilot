import { useState } from 'react';
import { Input, Button, Upload, Space, Typography, Tag, Segmented } from 'antd';
import {
  SendOutlined,
  PictureOutlined,
  DeleteOutlined,
  FileTextOutlined,
  CameraOutlined,
} from '@ant-design/icons';
import type { UploadFile } from 'antd';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';

const { TextArea } = Input;
const { Text } = Typography;

type InputMode = 'text' | 'drawing';

export interface InputPanelProps {
  onSendText: (text: string) => void;
  onSendImage: (file: File) => void;
  disabled?: boolean;
  loading?: boolean;
}

export default function InputPanel({
  onSendText,
  onSendImage,
  disabled = false,
  loading = false,
}: InputPanelProps) {
  const [mode, setMode] = useState<InputMode>('text');
  const dt = useDesignTokens();
  const [text, setText] = useState('');
  const [imageFile, setImageFile] = useState<UploadFile | null>(null);

  const handleSend = () => {
    if (mode === 'drawing' && imageFile?.originFileObj) {
      onSendImage(imageFile.originFileObj);
      setImageFile(null);
    } else if (mode === 'text' && text.trim()) {
      onSendText(text.trim());
      setText('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const canSend =
    mode === 'text' ? text.trim().length > 0 : imageFile !== null;

  return (
    <div>
      <Text strong style={{ display: 'block', marginBottom: 8 }}>
        输入方式
      </Text>
      <Segmented
        block
        value={mode}
        onChange={(v) => setMode(v as InputMode)}
        options={[
          { label: '文本描述', value: 'text', icon: <FileTextOutlined /> },
          { label: '工程图纸', value: 'drawing', icon: <CameraOutlined /> },
        ]}
        disabled={disabled}
        style={{ marginBottom: 16 }}
      />

      {mode === 'text' && (
        <>
          <TextArea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="描述你想要的零件，例如：做一个外径100mm的法兰盘，6个M10螺栓孔…"
            autoSize={{ minRows: 3, maxRows: 8 }}
            disabled={disabled}
            style={{ marginBottom: 8 }}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            Enter 发送，Shift+Enter 换行
          </Text>
        </>
      )}

      {mode === 'drawing' && (
        <div style={{ marginBottom: 8 }}>
          {imageFile ? (
            <div
              style={{
                padding: 12,
                borderRadius: 8,
                border: `1px dashed ${dt.color.border}`,
                textAlign: 'center',
              }}
            >
              <Tag
                closable
                onClose={() => setImageFile(null)}
                icon={<PictureOutlined />}
                style={{ fontSize: 13 }}
              >
                {imageFile.name}
              </Tag>
              <div style={{ marginTop: 8 }}>
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => setImageFile(null)}
                >
                  移除
                </Button>
              </div>
            </div>
          ) : (
            <Upload.Dragger
              accept="image/*"
              showUploadList={false}
              beforeUpload={(file) => {
                setImageFile({
                  uid: '-1',
                  name: file.name,
                  originFileObj: file,
                } as UploadFile);
                return false;
              }}
              disabled={disabled}
            >
              <p>
                <PictureOutlined style={{ fontSize: 32, color: dt.color.textTertiary }} />
              </p>
              <p>点击或拖拽上传工程图纸</p>
              <p style={{ color: dt.color.textTertiary, fontSize: 12 }}>
                支持 PNG、JPG 格式
              </p>
            </Upload.Dragger>
          )}
        </div>
      )}

      <Space style={{ width: '100%', justifyContent: 'flex-end', marginTop: 12 }}>
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={handleSend}
          loading={loading}
          disabled={disabled || !canSend}
        >
          {mode === 'text' ? '生成模型' : '分析图纸'}
        </Button>
      </Space>
    </div>
  );
}
