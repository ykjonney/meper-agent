/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import type { ThemeConfig } from 'antd';

export type ThemeMode = 'light' | 'dark';

export const lightTheme: ThemeConfig = {
  token: {
    colorPrimary: '#1677ff',
    borderRadius: 6,
    colorBgContainer: '#ffffff',
    colorBgLayout: '#f5f5f5',
    colorBorder: '#f0f0f0',
    colorBorderSecondary: '#f0f0f0',
    colorText: '#262626',
    colorTextSecondary: '#595959',
    colorTextTertiary: '#8c8c8c',
    colorTextQuaternary: '#bfbfbf',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif, "Apple Color Emoji", "Segoe UI Emoji"',
  },
  components: {
    Layout: {
      siderBg: '#ffffff',
      headerBg: '#ffffff',
      bodyBg: '#f5f5f5',
    },
    Menu: {
      itemBg: 'transparent',
      itemSelectedBg: '#e6f4ff',
      itemSelectedColor: '#1677ff',
      itemHoverBg: '#fafafa',
      itemHoverColor: '#262626',
      itemColor: '#595959',
      groupTitleColor: '#8c8c8c',
      iconSize: 16,
    },
    Dropdown: {
      colorBgElevated: '#ffffff',
    },
  },
};

export const darkTheme: ThemeConfig = {
  algorithm: undefined, // Will be set to theme.darkAlgorithm at usage site
  token: {
    colorPrimary: '#1677ff',
    borderRadius: 6,
    colorBgContainer: '#1f1f1f',
    colorBgLayout: '#141414',
    colorBorder: '#303030',
    colorBorderSecondary: '#303030',
    colorText: '#e8e8e8',
    colorTextSecondary: '#a6a6a6',
    colorTextTertiary: '#737373',
    colorTextQuaternary: '#595959',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif, "Apple Color Emoji", "Segoe UI Emoji"',
  },
  components: {
    Layout: {
      siderBg: '#1f1f1f',
      headerBg: '#1f1f1f',
      bodyBg: '#141414',
    },
    Menu: {
      itemBg: 'transparent',
      itemSelectedBg: '#111d2c',
      itemSelectedColor: '#1677ff',
      itemHoverBg: '#262626',
      itemHoverColor: '#e8e8e8',
      itemColor: '#a6a6a6',
      groupTitleColor: '#737373',
      iconSize: 16,
    },
    Dropdown: {
      colorBgElevated: '#1f1f1f',
    },
  },
};
