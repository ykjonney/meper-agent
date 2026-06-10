import type { Config } from 'tailwindcss'

/**
 * Tailwind CSS — Blue + White minimal theme
 *
 * Primary: #2563EB (Blue) — trust, professional, stable
 * Surface: Pure white + slate gray ladder
 * Font:    DM Sans
 * Style:   Linear / Vercel / Notion inspired minimalism
 */
const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#2563EB',
          hover: '#1D4ED8',
          active: '#1E40AF',
          light: '#60A5FA',
          bg: '#EFF6FF',
          'bg-strong': '#DBEAFE',
        },
        accent: {
          DEFAULT: '#F97316',
          hover: '#EA580C',
          bg: '#FFF7ED',
        },
        surface: {
          canvas: '#FFFFFF',
          secondary: '#F8FAFC',
          muted: '#F1F5F9',
        },
        success: { DEFAULT: '#10B981', bg: '#D1FAE5' },
        warning: { DEFAULT: '#F59E0B', bg: '#FEF3C7' },
        error: { DEFAULT: '#EF4444', bg: '#FEE2E2' },
        info: { DEFAULT: '#3B82F6', bg: '#DBEAFE' },
      },
      fontFamily: {
        sans: ['"DM Sans"', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', '"PingFang SC"', '"Microsoft YaHei"', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"SF Mono"', 'monospace'],
      },
      borderRadius: {
        sm: '6px',
        DEFAULT: '8px',
        md: '10px',
        lg: '12px',
        xl: '16px',
      },
      boxShadow: {
        card: '0 1px 3px 0 rgb(0 0 0 / 0.06), 0 1px 2px -1px rgb(0 0 0 / 0.06)',
        'card-hover': '0 4px 12px -2px rgb(0 0 0 / 0.08), 0 2px 6px -2px rgb(0 0 0 / 0.04)',
        nav: '0 1px 2px 0 rgb(0 0 0 / 0.05)',
        'blue-glow': '0 0 0 3px rgb(37 99 235 / 0.1)',
      },
    },
  },
  corePlugins: {
    preflight: false,
  },
  plugins: [],
}

export default config
