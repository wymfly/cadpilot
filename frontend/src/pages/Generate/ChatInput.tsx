import { useState } from 'react';
import { Input, Button, Upload, Space, Typography, Tag } from 'antd';
import {
  SendOutlined,
  PictureOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import type { UploadFile } from 'antd';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';

const { TextArea } = Input;
const { Text } = Typography;

export interface ChatInputProps {
  onSendText: (text: string) => void;
  onSendImage: (file: File) => void;
  disabled?: boolean;
  loading?: boolean;
  placeholder?: string;
}

export default function ChatInput({
  onSendText,
  onSendImage,
  disabled = false,
  loading = false,
  placeholder = '描述你想要的零件，例如：做一个外径100mm的法兰盘，6个M10螺栓孔…',
}: ChatInputProps) {
  const [text, setText] = useState('');
  const [imageFile, setImageFile] = useState<UploadFile | null>(null);

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed && !imageFile) return;

    if (imageFile?.originFileObj) {
      onSendImage(imageFile.originFileObj);
    } else if (trimmed) {
      onSendText(trimmed);
    }
    setText('');
    setImageFile(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const dt = useDesignTokens();

  return (
    <div
      style={{
        padding: 12,
        borderRadius: 8,
        border: `1px solid ${dt.color.border}`,
        background: dt.color.surface1,
      }}
    >
      {imageFile && (
        <div style={{ marginBottom: 8 }}>
          <Tag
            closable
            onClose={() => setImageFile(null)}
            icon={<PictureOutlined />}
          >
            {imageFile.name}
          </Tag>
        </div>
      )}

      <TextArea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        autoSize={{ minRows: 2, maxRows: 5 }}
        disabled={disabled}
        style={{ border: 'none', boxShadow: 'none', resize: 'none' }}
      />

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 8,
        }}
      >
        <Space>
          <Upload
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
            <Button
              icon={<PictureOutlined />}
              size="small"
              disabled={disabled}
            >
              上传图纸
            </Button>
          </Upload>
          {imageFile && (
            <Button
              icon={<DeleteOutlined />}
              size="small"
              danger
              onClick={() => setImageFile(null)}
            >
              移除
            </Button>
          )}
        </Space>

        <Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Enter 发送, Shift+Enter 换行
          </Text>
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={handleSend}
            loading={loading}
            disabled={disabled || (!text.trim() && !imageFile)}
          >
            发送
          </Button>
        </Space>
      </div>
    </div>
  );
}
