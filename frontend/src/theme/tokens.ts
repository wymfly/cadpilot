/**
 * Industrial Design Token System
 *
 * Dark-first palette inspired by Fusion 360, Blender 4.x, VS Code.
 * Every color has a dark/light variant resolved at runtime via useDesignTokens().
 */

export type ThemeMode = 'dark' | 'light';

export interface DualColor {
  dark: string;
  light: string;
}

// ---------------------------------------------------------------------------
// Color Tokens
// ---------------------------------------------------------------------------

export const colors = {
  // Surfaces (layered depth)
  surface0: { dark: '#0D0F12', light: '#FAFBFC' } as DualColor,
  surface1: { dark: '#16191D', light: '#FFFFFF' } as DualColor,
  surface2: { dark: '#20242A', light: '#F5F6F8' } as DualColor,
  surface3: { dark: '#2A2F38', light: '#ECEEF1' } as DualColor,

  // Brand / Action
  primary: { dark: '#00A3FF', light: '#0088DD' } as DualColor,
  action: { dark: '#FF5500', light: '#E64D00' } as DualColor,

  // Semantic
  success: { dark: '#00E676', light: '#00C853' } as DualColor,
  warning: { dark: '#FFB300', light: '#F5A000' } as DualColor,
  error: { dark: '#FF3333', light: '#E53030' } as DualColor,

  // Text
  textPrimary: { dark: '#E2E8F0', light: '#1A202C' } as DualColor,
  textSecondary: { dark: '#8A95A5', light: '#718096' } as DualColor,
  textTertiary: { dark: '#6B7789', light: '#A0AEC0' } as DualColor,

  // Borders
  border: { dark: '#2D323A', light: '#E2E8F0' } as DualColor,
  borderHover: { dark: '#3D434D', light: '#CBD5E0' } as DualColor,

  // Special
  glassBg: {
    dark: 'rgba(22,25,29,0.85)',
    light: 'rgba(255,255,255,0.90)',
  } as DualColor,
  overlay: { dark: 'rgba(0,0,0,0.6)', light: 'rgba(0,0,0,0.3)' } as DualColor,
} as const;

// ---------------------------------------------------------------------------
// Radius
// ---------------------------------------------------------------------------

export const radii = { sm: 4, md: 8, lg: 12 } as const;

// ---------------------------------------------------------------------------
// Spacing
// ---------------------------------------------------------------------------

export const spacing = {
  panelPadding: 16,
  sectionGap: 12,
  itemGap: 8,
} as const;

// ---------------------------------------------------------------------------
// Typography
// ---------------------------------------------------------------------------

export const typography = {
  fontUI: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
  fontMono: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
  panelTitle: {
    size: 12,
    weight: 600,
    transform: 'uppercase' as const,
    letterSpacing: '1px',
  },
  body: { size: 13, weight: 400 },
  data: { size: 12, weight: 500 },
} as const;

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

export const layout = {
  topNavHeight: 48,
  leftPanelWidth: 320,
  rightPanelWidth: 280,
} as const;

// ---------------------------------------------------------------------------
// Shadows
// ---------------------------------------------------------------------------

export const shadows = {
  panel: {
    dark: '0 4px 24px rgba(0,0,0,0.4), 0 0 1px rgba(0,163,255,0.15)',
    light: '0 4px 24px rgba(0,0,0,0.08), 0 0 1px rgba(0,0,0,0.1)',
  } as DualColor,
  hover: {
    dark: '0 0 0 1px rgba(0,163,255,0.3)',
    light: '0 0 0 1px rgba(0,136,221,0.3)',
  } as DualColor,
} as const;

// ---------------------------------------------------------------------------
// Motion
// ---------------------------------------------------------------------------

export const motion = {
  panelSlide: 'cubic-bezier(0.16, 1, 0.3, 1)',
  panelDuration: '180ms',
} as const;
