import { useCallback } from 'react';
import { Layout, Button, Tooltip } from 'antd';
import { SunOutlined, MoonOutlined } from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTheme } from '../contexts/ThemeContext.tsx';

const { Header } = Layout;

interface NavTab {
  key: string;
  path: string;
  label: string;
}

const TABS: NavTab[] = [
  { key: 'precision', path: '/precision', label: '精密建模' },
  { key: 'organic', path: '/organic', label: '创意雕塑' },
  { key: 'library', path: '/library', label: '零件库' },
  { key: 'templates', path: '/templates', label: '模板' },
  { key: 'standards', path: '/standards', label: '标准' },
  { key: 'benchmark', path: '/benchmark', label: '评测' },
  { key: 'settings', path: '/settings', label: '设置' },
];

function getActiveTab(pathname: string): string {
  if (pathname.startsWith('/organic')) return 'organic';
  if (pathname.startsWith('/library')) return 'library';
  if (pathname.startsWith('/templates')) return 'templates';
  if (pathname.startsWith('/standards')) return 'standards';
  if (pathname.startsWith('/benchmark')) return 'benchmark';
  if (pathname.startsWith('/settings')) return 'settings';
  return 'precision';
}

export default function TopNav() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isDark, toggleTheme } = useTheme();

  const activeTab = getActiveTab(location.pathname);

  const handleTabClick = useCallback(
    (tab: NavTab) => {
      navigate(tab.path);
    },
    [navigate],
  );

  return (
    <Header
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '0 24px',
        height: 48,
        lineHeight: '48px',
        borderBottom: `1px solid ${isDark ? '#303030' : '#f0f0f0'}`,
        background: isDark ? '#1f1f1f' : '#ffffff',
      }}
    >
      {/* Logo */}
      <div
        style={{
          fontWeight: 700,
          fontSize: 16,
          color: isDark ? '#4096ff' : '#1677ff',
          marginRight: 32,
          cursor: 'pointer',
          whiteSpace: 'nowrap',
        }}
        onClick={() => navigate('/precision')}
      >
        CAD3Dify
      </div>

      {/* Tab 导航 */}
      <nav style={{ display: 'flex', gap: 4, flex: 1 }}>
        {TABS.map((tab) => {
          const isActive = tab.key === activeTab;
          return (
            <button
              key={tab.key}
              onClick={() => handleTabClick(tab)}
              style={{
                padding: '6px 16px',
                border: 'none',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 14,
                fontWeight: isActive ? 600 : 400,
                color: isActive
                  ? isDark ? '#4096ff' : '#1677ff'
                  : isDark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)',
                background: isActive
                  ? isDark ? 'rgba(64,150,255,0.1)' : 'rgba(22,119,255,0.06)'
                  : 'transparent',
                transition: 'all 0.2s',
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </nav>

      {/* 主题切换 */}
      <Tooltip title={isDark ? '切换亮色模式' : '切换暗色模式'}>
        <Button
          type="text"
          icon={isDark ? <SunOutlined /> : <MoonOutlined />}
          onClick={toggleTheme}
          style={{
            color: isDark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)',
          }}
        />
      </Tooltip>
    </Header>
  );
}
