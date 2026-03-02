import { theme as antdTheme, type ThemeConfig } from 'antd';
import { colors, radii, typography } from './tokens.ts';
import type { ThemeMode } from './tokens.ts';

/**
 * Build a complete Ant Design theme config for the given mode.
 * Covers global token + component-level overrides.
 */
export function getAntdThemeConfig(isDark: boolean): ThemeConfig {
  const mode: ThemeMode = isDark ? 'dark' : 'light';

  return {
    algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      // Brand
      colorPrimary: colors.primary[mode],
      colorError: colors.error[mode],
      colorWarning: colors.warning[mode],
      colorSuccess: colors.success[mode],

      // Surfaces
      colorBgContainer: colors.surface1[mode],
      colorBgElevated: colors.surface2[mode],
      colorBgLayout: colors.surface0[mode],

      // Text
      colorText: colors.textPrimary[mode],
      colorTextSecondary: colors.textSecondary[mode],
      colorTextTertiary: colors.textTertiary[mode],

      // Borders
      colorBorder: colors.border[mode],
      colorBorderSecondary: colors.border[mode],

      // Radius
      borderRadius: radii.md,
      borderRadiusSM: radii.sm,
      borderRadiusLG: radii.lg,

      // Typography
      fontFamily: typography.fontUI,
      fontSize: typography.body.size,

      // Motion
      motionDurationMid: '180ms',
      motionEaseInOut: 'cubic-bezier(0.16, 1, 0.3, 1)',
    },
    components: {
      Card: {
        colorBgContainer: colors.surface1[mode],
        borderRadiusLG: radii.lg,
        paddingLG: 16,
      },
      Button: {
        borderRadius: radii.sm,
        controlHeight: 32,
        fontWeight: 500,
      },
      Input: {
        colorBgContainer: colors.surface2[mode],
        borderRadius: radii.sm,
      },
      Select: {
        colorBgContainer: colors.surface2[mode],
        borderRadius: radii.sm,
      },
      Tabs: {
        colorBorderSecondary: colors.border[mode],
        itemColor: colors.textSecondary[mode],
        itemActiveColor: colors.primary[mode],
        itemSelectedColor: colors.primary[mode],
        inkBarColor: colors.primary[mode],
      },
      Steps: {
        colorPrimary: colors.primary[mode],
      },
      Tag: {
        borderRadiusSM: radii.sm,
      },
      Table: {
        colorBgContainer: colors.surface1[mode],
        headerBg: colors.surface2[mode],
        borderColor: colors.border[mode],
      },
      Collapse: {
        colorBgContainer: 'transparent',
        headerBg: 'transparent',
        contentBg: 'transparent',
      },
      Segmented: {
        colorBgLayout: colors.surface2[mode],
        borderRadius: radii.sm,
        itemSelectedBg: colors.primary[mode],
        itemSelectedColor: '#FFFFFF',
      },
      Switch: {
        colorPrimary: colors.primary[mode],
      },
      Slider: {
        colorPrimaryBorder: colors.primary[mode],
        colorPrimaryBorderHover: colors.primary[mode],
      },
    },
  };
}
