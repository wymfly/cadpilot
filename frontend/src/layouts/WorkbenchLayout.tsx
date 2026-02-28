import { useState, useEffect, useCallback, useMemo, type ReactNode } from 'react';
import { Layout, Button, Drawer } from 'antd';
import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { Outlet, useOutletContext } from 'react-router-dom';
import TopNav from './TopNav.tsx';
import { useTheme } from '../contexts/ThemeContext.tsx';

const LEFT_WIDTH = 240;
const RIGHT_WIDTH = 300;
const MOBILE_BREAKPOINT = 768;
const STORAGE_KEY_LEFT = 'cad3dify-panel-left';
const STORAGE_KEY_RIGHT = 'cad3dify-panel-right';

function getStoredCollapsed(key: string): boolean {
  try {
    return localStorage.getItem(key) === 'true';
  } catch {
    return false;
  }
}

function setStoredCollapsed(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, String(value));
  } catch {
    // ignore
  }
}

/** 三栏工作台布局上下文，子页面通过此注入面板内容 */
export interface WorkbenchPanels {
  left?: ReactNode;
  right?: ReactNode;
}

// 使用 Outlet context 传递面板内容
export interface WorkbenchOutletContext {
  setPanels: (panels: WorkbenchPanels) => void;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
}

/** 全宽页面包装器：不使用左右面板，中央区域占满 */
export function FullWidthPage({ children }: { children: ReactNode }) {
  const { setPanels } = useOutletContext<WorkbenchOutletContext>();
  useEffect(() => {
    setPanels({});
  }, [setPanels]);
  return (
    <div style={{ padding: 24, height: '100%', overflow: 'auto' }}>
      {children}
    </div>
  );
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    const mql = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, [query]);

  return matches;
}

export default function WorkbenchLayout() {
  const { isDark } = useTheme();
  const isMobile = useMediaQuery(`(max-width: ${MOBILE_BREAKPOINT}px)`);

  const [leftCollapsed, setLeftCollapsed] = useState(() =>
    getStoredCollapsed(STORAGE_KEY_LEFT),
  );
  const [rightCollapsed, setRightCollapsed] = useState(() =>
    getStoredCollapsed(STORAGE_KEY_RIGHT),
  );
  const [panels, setPanels] = useState<WorkbenchPanels>({});

  // 移动端 drawer 状态
  const [leftDrawerOpen, setLeftDrawerOpen] = useState(false);
  const [rightDrawerOpen, setRightDrawerOpen] = useState(false);

  const toggleLeft = useCallback(() => {
    if (isMobile) {
      setLeftDrawerOpen((v) => !v);
    } else {
      setLeftCollapsed((prev) => {
        const next = !prev;
        setStoredCollapsed(STORAGE_KEY_LEFT, next);
        return next;
      });
    }
  }, [isMobile]);

  const toggleRight = useCallback(() => {
    if (isMobile) {
      setRightDrawerOpen((v) => !v);
    } else {
      setRightCollapsed((prev) => {
        const next = !prev;
        setStoredCollapsed(STORAGE_KEY_RIGHT, next);
        return next;
      });
    }
  }, [isMobile]);

  const outletContext = useMemo<WorkbenchOutletContext>(
    () => ({ setPanels, leftCollapsed, rightCollapsed }),
    [setPanels, leftCollapsed, rightCollapsed],
  );

  const panelBg = isDark ? '#1f1f1f' : '#ffffff';
  const layoutBg = isDark ? '#141414' : '#f5f5f5';
  const borderColor = isDark ? '#303030' : '#f0f0f0';

  // 面板折叠按钮样式
  const collapseButtonStyle = {
    position: 'absolute' as const,
    top: '50%',
    transform: 'translateY(-50%)',
    zIndex: 10,
    width: 20,
    height: 40,
    padding: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 4,
    fontSize: 12,
  };

  if (isMobile) {
    // 移动端：单列 + 底部抽屉
    return (
      <Layout style={{ minHeight: '100vh', background: layoutBg }}>
        <TopNav />
        <Layout.Content style={{ flex: 1, position: 'relative' }}>
          <Outlet context={outletContext} />

          {/* 左面板浮动按钮 */}
          {panels.left && (
            <Button
              size="small"
              icon={<RightOutlined />}
              onClick={toggleLeft}
              style={{
                position: 'fixed',
                bottom: 80,
                left: 12,
                zIndex: 100,
              }}
            />
          )}
          {/* 右面板浮动按钮 */}
          {panels.right && (
            <Button
              size="small"
              icon={<LeftOutlined />}
              onClick={toggleRight}
              style={{
                position: 'fixed',
                bottom: 80,
                right: 12,
                zIndex: 100,
              }}
            />
          )}

          <Drawer
            placement="bottom"
            open={leftDrawerOpen}
            onClose={() => setLeftDrawerOpen(false)}
            height="60vh"
            title="操作面板"
            styles={{ body: { padding: 16 } }}
          >
            {panels.left}
          </Drawer>

          <Drawer
            placement="bottom"
            open={rightDrawerOpen}
            onClose={() => setRightDrawerOpen(false)}
            height="60vh"
            title="详情"
            styles={{ body: { padding: 16 } }}
          >
            {panels.right}
          </Drawer>
        </Layout.Content>
      </Layout>
    );
  }

  const hasLeftPanel = !!panels.left;
  const hasRightPanel = !!panels.right;

  // 桌面端：三栏布局（无面板内容时自动全宽）
  return (
    <Layout style={{ minHeight: '100vh', background: layoutBg }}>
      <TopNav />
      <div
        style={{
          display: 'flex',
          flex: 1,
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        {/* 左面板（仅在有内容时渲染） */}
        {hasLeftPanel && (
          <>
            <div
              style={{
                width: leftCollapsed ? 0 : LEFT_WIDTH,
                minWidth: leftCollapsed ? 0 : LEFT_WIDTH,
                background: panelBg,
                borderRight: leftCollapsed ? 'none' : `1px solid ${borderColor}`,
                overflow: leftCollapsed ? 'hidden' : 'auto',
                transition: 'width 0.2s, min-width 0.2s',
                position: 'relative',
                padding: leftCollapsed ? 0 : 16,
              }}
            >
              {!leftCollapsed && panels.left}
            </div>

            <Button
              type="text"
              size="small"
              icon={leftCollapsed ? <RightOutlined /> : <LeftOutlined />}
              onClick={toggleLeft}
              style={{
                ...collapseButtonStyle,
                left: leftCollapsed ? 0 : LEFT_WIDTH - 10,
              }}
            />
          </>
        )}

        {/* 中央区域 */}
        <div
          style={{
            flex: 1,
            overflow: 'hidden',
            position: 'relative',
            background: layoutBg,
          }}
        >
          <Outlet context={outletContext} />
        </div>

        {/* 右面板（仅在有内容时渲染） */}
        {hasRightPanel && (
          <>
            <Button
              type="text"
              size="small"
              icon={rightCollapsed ? <LeftOutlined /> : <RightOutlined />}
              onClick={toggleRight}
              style={{
                ...collapseButtonStyle,
                right: rightCollapsed ? 0 : RIGHT_WIDTH - 10,
              }}
            />

            <div
              style={{
                width: rightCollapsed ? 0 : RIGHT_WIDTH,
                minWidth: rightCollapsed ? 0 : RIGHT_WIDTH,
                background: panelBg,
                borderLeft: rightCollapsed ? 'none' : `1px solid ${borderColor}`,
                overflow: rightCollapsed ? 'hidden' : 'auto',
                transition: 'width 0.2s, min-width 0.2s',
                position: 'relative',
                padding: rightCollapsed ? 0 : 16,
              }}
            >
              {!rightCollapsed && panels.right}
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
