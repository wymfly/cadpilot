import { useCallback } from 'react';
import { Layout, Button, Tooltip } from 'antd';
import { SunOutlined, MoonOutlined } from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTheme } from '../contexts/ThemeContext.tsx';
import { useDesignTokens } from '../theme/useDesignTokens.ts';

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
  const { toggleTheme } = useTheme();
  const dt = useDesignTokens();

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
        height: dt.layout.topNavHeight,
        lineHeight: `${dt.layout.topNavHeight}px`,
        borderBottom: `1px solid ${dt.color.border}`,
        background: dt.color.surface1,
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
      }}
    >
      {/* Logo — JetBrains Mono + primary color */}
      <div
        style={{
          fontFamily: dt.typography.fontMono,
          fontWeight: 700,
          fontSize: 16,
          color: dt.color.primary,
          marginRight: 32,
          cursor: 'pointer',
          whiteSpace: 'nowrap',
          letterSpacing: '2px',
        }}
        onClick={() => navigate('/precision')}
      >
        CAD3Dify
      </div>

      {/* Tab 导航 — industrial uppercase */}
      <nav style={{ display: 'flex', gap: 2, flex: 1 }}>
        {TABS.map((tab) => {
          const isActive = tab.key === activeTab;
          return (
            <button
              key={tab.key}
              onClick={() => handleTabClick(tab)}
              style={{
                padding: '6px 14px',
                border: 'none',
                borderRadius: 0,
                cursor: 'pointer',
                fontSize: dt.typography.panelTitle.size,
                fontWeight: dt.typography.panelTitle.weight,
                fontFamily: dt.typography.fontUI,
                textTransform: dt.typography.panelTitle.transform,
                letterSpacing: dt.typography.panelTitle.letterSpacing,
                color: isActive ? dt.color.primary : dt.color.textSecondary,
                background: 'transparent',
                borderBottom: isActive ? `2px solid ${dt.color.primary}` : '2px solid transparent',
                transition: 'color 150ms, border-color 150ms',
                lineHeight: `${dt.layout.topNavHeight - 14}px`,
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </nav>

      {/* 主题切换 */}
      <Tooltip title={dt.isDark ? '切换亮色模式' : '切换暗色模式'}>
        <Button
          type="text"
          icon={dt.isDark ? <SunOutlined /> : <MoonOutlined />}
          onClick={toggleTheme}
          style={{
            color: dt.color.textSecondary,
          }}
        />
      </Tooltip>
    </Header>
  );
}
