import { Button, Space } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';

interface OrganicDownloadButtonsProps {
  stlUrl: string | null;
  threemfUrl: string | null;
}

export default function OrganicDownloadButtons({ stlUrl, threemfUrl }: OrganicDownloadButtonsProps) {
  if (!stlUrl && !threemfUrl) return null;

  return (
    <Space>
      {stlUrl && (
        <Button icon={<DownloadOutlined />} href={stlUrl} download>
          STL
        </Button>
      )}
      {threemfUrl && (
        <Button icon={<DownloadOutlined />} href={threemfUrl} download>
          3MF
        </Button>
      )}
    </Space>
  );
}
