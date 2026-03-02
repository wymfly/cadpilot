import { Button, Space } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';

interface OrganicDownloadButtonsProps {
  modelUrl: string | null;
  stlUrl: string | null;
  threemfUrl: string | null;
}

export default function OrganicDownloadButtons({ modelUrl, stlUrl, threemfUrl }: OrganicDownloadButtonsProps) {
  if (!modelUrl && !stlUrl && !threemfUrl) return null;

  return (
    <Space wrap style={{ marginTop: 12 }}>
      {modelUrl && (
        <Button icon={<DownloadOutlined />} href={modelUrl} download="model.glb">
          GLB
        </Button>
      )}
      {stlUrl && (
        <Button icon={<DownloadOutlined />} href={stlUrl} download="model.stl">
          STL
        </Button>
      )}
      {threemfUrl && (
        <Button icon={<DownloadOutlined />} href={threemfUrl} download="model.3mf">
          3MF
        </Button>
      )}
    </Space>
  );
}
