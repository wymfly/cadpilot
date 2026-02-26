import { Tabs, Typography } from 'antd';
import { BookOutlined, SearchOutlined } from '@ant-design/icons';
import StandardBrowser from './StandardBrowser.tsx';
import StandardQuery from './StandardQuery.tsx';

const { Title } = Typography;

export default function Standards() {
  return (
    <div>
      <Title level={3} style={{ marginBottom: 16 }}>
        工程标准
      </Title>
      <Tabs
        defaultActiveKey="browse"
        items={[
          {
            key: 'browse',
            label: (
              <span>
                <BookOutlined /> 标准浏览
              </span>
            ),
            children: <StandardBrowser />,
          },
          {
            key: 'query',
            label: (
              <span>
                <SearchOutlined /> 参数查询
              </span>
            ),
            children: <StandardQuery />,
          },
        ]}
      />
    </div>
  );
}
