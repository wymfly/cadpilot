import { Layout, Menu } from 'antd';
import {
  HomeOutlined,
  ExperimentOutlined,
  AppstoreOutlined,
  BookOutlined,
  BarChartOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';

const { Header, Sider, Content } = Layout;

const menuItems = [
  { key: '/', icon: <HomeOutlined />, label: '首页' },
  { key: '/generate', icon: <ExperimentOutlined />, label: '生成' },
  { key: '/templates', icon: <AppstoreOutlined />, label: '模板' },
  { key: '/standards', icon: <BookOutlined />, label: '标准' },
  { key: '/benchmark', icon: <BarChartOutlined />, label: '评测' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
];

export default function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();

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
          selectedKeys={[location.pathname]}
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
            AI 驱动的 2D → 3D CAD 生成平台
          </span>
        </Header>
        <Content style={{ margin: 24, padding: 24, background: '#fff', borderRadius: 8 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
