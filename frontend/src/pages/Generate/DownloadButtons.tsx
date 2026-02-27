import { Button, Space, message } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';

interface DownloadButtonsProps {
  jobId: string;
}

export default function DownloadButtons({ jobId }: DownloadButtonsProps) {
  const handleDownload = async (format: string) => {
    try {
      const resp = await fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: jobId,
          config: { format },
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: '下载失败' }));
        message.error(err.detail || '下载失败');
        return;
      }
      const blob = await resp.blob();
      const ext = format === 'gltf' ? 'glb' : format;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `model.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      message.error('下载请求失败');
    }
  };

  return (
    <Space>
      <Button icon={<DownloadOutlined />} onClick={() => handleDownload('step')} type="primary">
        下载 STEP
      </Button>
      <Button icon={<DownloadOutlined />} onClick={() => handleDownload('stl')}>
        下载 STL
      </Button>
      <Button icon={<DownloadOutlined />} onClick={() => handleDownload('3mf')}>
        下载 3MF
      </Button>
    </Space>
  );
}
