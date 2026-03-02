import { useState, useEffect, useCallback, useMemo, type ReactNode } from 'react';
import { Layout, Button, Drawer } from 'antd';
import {
  LeftOutlined,
  RightOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons';
import { Outlet, useOutletContext } from 'react-router-dom';
import TopNav from './TopNav.tsx';
import { useDesignTokens } from '../theme/useDesignTokens.ts';
import Crosshair from '../components/decorative/Crosshair.tsx';

const MOBILE_BREAKPOINT = 768;
const STORAGE_KEY_LEFT = 'cadpilot-panel-left';
const STORAGE_KEY_RIGHT = 'cadpilot-panel-right';

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
  const dt = useDesignTokens();
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

  if (isMobile) {
    return (
      <Layout style={{ minHeight: '100vh', background: dt.color.surface0 }}>
        <TopNav />
        <Layout.Content style={{ flex: 1, position: 'relative' }}>
          <Outlet context={outletContext} />

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

  // 面板样式：浮动 HUD（磨砂玻璃）
  const panelBase: React.CSSProperties = {
    position: 'absolute',
    top: 12,
    bottom: 12,
    zIndex: 20,
    background: dt.color.glassBg,
    backdropFilter: 'blur(12px)',
    WebkitBackdropFilter: 'blur(12px)',
    border: `1px solid ${dt.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}`,
    borderRadius: dt.radius.lg,
    padding: dt.spacing.panelPadding,
    overflow: 'auto',
    boxShadow: dt.shadow.panel,
    transition: `transform ${dt.motion.panelDuration} ${dt.motion.panelSlide}, opacity ${dt.motion.panelDuration} ${dt.motion.panelSlide}`,
  };

  // 折叠按钮样式
  const collapseBtn: React.CSSProperties = {
    position: 'absolute',
    top: 8,
    zIndex: 30,
    width: 28,
    height: 28,
    padding: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 12,
    borderRadius: dt.radius.sm,
    opacity: 0.7,
  };

  return (
    <Layout style={{ minHeight: '100vh', background: dt.color.surface0 }}>
      <TopNav />
      <div
        style={{
          flex: 1,
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        {/* 中央区域（全画幅） */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            overflow: 'hidden',
          }}
        >
          <Outlet context={outletContext} />
        </div>

        {/* 左面板（浮动 HUD） */}
        {hasLeftPanel && (
          <>
            <div
              className="hud-panel"
              aria-hidden={leftCollapsed}
              style={{
                ...panelBase,
                left: 12,
                width: dt.layout.leftPanelWidth,
                transform: leftCollapsed ? 'translateX(-110%)' : 'translateX(0)',
                opacity: leftCollapsed ? 0 : 1,
                pointerEvents: leftCollapsed ? 'none' : 'auto',
              }}
            >
              <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 1 }}>
                <Crosshair />
              </div>
              {panels.left}
            </div>

            <Button
              type="text"
              size="small"
              aria-label={leftCollapsed ? '展开左面板' : '折叠左面板'}
              icon={leftCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={toggleLeft}
              style={{
                ...collapseBtn,
                left: leftCollapsed ? 12 : dt.layout.leftPanelWidth + 12 - 28 - 4,
              }}
            />
          </>
        )}

        {/* 右面板（浮动 HUD） */}
        {hasRightPanel && (
          <>
            <div
              className="hud-panel"
              aria-hidden={rightCollapsed}
              style={{
                ...panelBase,
                right: 12,
                width: dt.layout.rightPanelWidth,
                transform: rightCollapsed ? 'translateX(110%)' : 'translateX(0)',
                opacity: rightCollapsed ? 0 : 1,
                pointerEvents: rightCollapsed ? 'none' : 'auto',
              }}
            >
              <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 1 }}>
                <Crosshair />
              </div>
              {panels.right}
            </div>

            <Button
              type="text"
              size="small"
              aria-label={rightCollapsed ? '展开右面板' : '折叠右面板'}
              icon={rightCollapsed ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />}
              onClick={toggleRight}
              style={{
                ...collapseBtn,
                right: rightCollapsed ? 12 : dt.layout.rightPanelWidth + 12 - 28 - 4,
              }}
            />
          </>
        )}
      </div>
    </Layout>
  );
}
