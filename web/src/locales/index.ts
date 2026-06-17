/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import zhCN from './zh-CN';
import en from './en';
import zhTW from './zh-TW';

export type LocaleType = 'zh-CN' | 'en' | 'zh-TW';

export const defaultLocale: LocaleType = 'zh-CN';

export const translations: Record<LocaleType, typeof zhCN> = {
  'zh-CN': zhCN,
  'en': en,
  'zh-TW': zhTW,
};
