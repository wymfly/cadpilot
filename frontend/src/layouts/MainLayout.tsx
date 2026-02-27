import { useState } from 'react';
import { Layout, Menu } from 'antd';
import {
  HomeOutlined,
  ExperimentOutlined,
  AppstoreOutlined,
  BookOutlined,
  BarChartOutlined,
  SettingOutlined,
  BulbOutlined,
} from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';

const { Header, Sider, Content } = Layout;

const menuItems = [
  { key: '/', icon: <HomeOutlined />, label: '首页' },
  {
    key: 'precision',
    icon: <ExperimentOutlined />,
    label: '精密建模',
    children: [
      { key: '/generate', label: '文本/图纸生成' },
      { key: '/templates', icon: <AppstoreOutlined />, label: '参数化模板' },
      { key: '/standards', icon: <BookOutlined />, label: '工程标准' },
      { key: '/benchmark', icon: <BarChartOutlined />, label: '评测基准' },
    ],
  },
  { key: '/generate/organic', icon: <BulbOutlined />, label: '创意雕塑' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
];

const getSelectedKey = (pathname: string): string => {
  if (pathname.startsWith('/benchmark')) return '/benchmark';
  if (pathname.startsWith('/generate/organic')) return '/generate/organic';
  if (pathname.startsWith('/generate')) return '/generate';
  return pathname;
};

const getOpenKeys = (pathname: string): string[] => {
  const precisionPaths = ['/generate', '/templates', '/standards', '/benchmark'];
  if (
    precisionPaths.some((p) => pathname.startsWith(p)) &&
    !pathname.startsWith('/generate/organic')
  ) {
    return ['precision'];
  }
  return [];
};

export default function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [openKeys, setOpenKeys] = useState<string[]>(getOpenKeys(location.pathname));

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        breakpoint="lg"
        collapsedWidth={56}
        style={{ background: '#fff' }}
      >
        <div
          style={{
            height: 48,
            margin: 12,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 700,
            fontSize: 16,
            color: '#1677ff',
          }}
        >
          CAD3Dify
        </div>
        <Menu
          mode="inline"
          selectedKeys={[getSelectedKey(location.pathname)]}
          openKeys={openKeys}
          onOpenChange={setOpenKeys}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderRight: 0 }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            borderBottom: '1px solid #f0f0f0',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <span style={{ fontSize: 14, color: '#999' }}>
            AI 驱动的 3D 模型生成平台
          </span>
        </Header>
        <Content style={{ margin: 24, padding: 24, background: '#fff', borderRadius: 8 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
