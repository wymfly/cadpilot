import { useMemo } from 'react';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  colors,
  radii,
  spacing,
  typography,
  layout,
  shadows,
  motion,
  type ThemeMode,
} from './tokens.ts';

/** Resolved color values for the current theme mode. */
export interface ResolvedColors {
  surface0: string;
  surface1: string;
  surface2: string;
  surface3: string;
  primary: string;
  action: string;
  success: string;
  warning: string;
  error: string;
  textPrimary: string;
  textSecondary: string;
  textTertiary: string;
  border: string;
  borderHover: string;
  glassBg: string;
  overlay: string;
}

function resolveColors(mode: ThemeMode): ResolvedColors {
  return {
    surface0: colors.surface0[mode],
    surface1: colors.surface1[mode],
    surface2: colors.surface2[mode],
    surface3: colors.surface3[mode],
    primary: colors.primary[mode],
    action: colors.action[mode],
    success: colors.success[mode],
    warning: colors.warning[mode],
    error: colors.error[mode],
    textPrimary: colors.textPrimary[mode],
    textSecondary: colors.textSecondary[mode],
    textTertiary: colors.textTertiary[mode],
    border: colors.border[mode],
    borderHover: colors.borderHover[mode],
    glassBg: colors.glassBg[mode],
    overlay: colors.overlay[mode],
  };
}

export interface DesignTokens {
  color: ResolvedColors;
  radius: typeof radii;
  spacing: typeof spacing;
  typography: typeof typography;
  layout: typeof layout;
  shadow: { panel: string; hover: string };
  motion: typeof motion;
  isDark: boolean;
}

export function useDesignTokens(): DesignTokens {
  const { isDark } = useTheme();
  const mode: ThemeMode = isDark ? 'dark' : 'light';

  return useMemo(
    () => ({
      color: resolveColors(mode),
      radius: radii,
      spacing,
      typography,
      layout,
      shadow: {
        panel: shadows.panel[mode],
        hover: shadows.hover[mode],
      },
      motion,
      isDark,
    }),
    [isDark, mode],
  );
}
