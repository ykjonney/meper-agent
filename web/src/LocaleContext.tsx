/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { translations, LocaleType, defaultLocale } from './locales';
export type { LocaleType };
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import zhTW from 'antd/locale/zh_TW';
import 'dayjs/locale/zh-cn';
import 'dayjs/locale/en';
import 'dayjs/locale/zh-tw';
import dayjs from 'dayjs';

const STORAGE_KEY = 'agentplat_locale';

interface LocaleContextType {
  locale: LocaleType;
  setLocale: (locale: LocaleType) => void;
  t: (key: string) => string;
}

const LocaleContext = createContext<LocaleContextType | null>(null);

/** Maps our LocaleType to antd locale objects */
const antdLocaleMap: Record<LocaleType, unknown> = {
  'zh-CN': zhCN,
  'en': enUS,
  'zh-TW': zhTW,
};

/** Maps our LocaleType to dayjs locale strings */
const dayjsLocaleMap: Record<LocaleType, string> = {
  'zh-CN': 'zh-cn',
  'en': 'en',
  'zh-TW': 'zh-tw',
};

export function LocaleProvider({ children }: { children?: React.ReactNode }) {
  const [locale, setLocaleState] = useState<LocaleType>(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && (saved === 'zh-CN' || saved === 'en' || saved === 'zh-TW')) {
      return saved as LocaleType;
    }
    return defaultLocale;
  });

  // Persist locale and sync dayjs locale
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, locale);
    dayjs.locale(dayjsLocaleMap[locale]);
  }, [locale]);

  const setLocale = useCallback((newLocale: LocaleType) => {
    setLocaleState(newLocale);
  }, []);

  const t = useCallback((key: string): string => {
    const keys = key.split('.');
    let result: unknown = translations[locale];
    for (const k of keys) {
      if (result && typeof result === 'object' && k in (result as Record<string, unknown>)) {
        result = (result as Record<string, unknown>)[k];
      } else {
        return key;
      }
    }
    return typeof result === 'string' ? result : key;
  }, [locale]);

  return (
    <LocaleContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </LocaleContext.Provider>
  );
}

export function useTranslation() {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error('useTranslation must be used within a LocaleProvider');
  return ctx;
}

/** Returns the antd locale object for the current locale */
export function useAntdLocale() {
  const { locale } = useTranslation();
  return antdLocaleMap[locale];
}
