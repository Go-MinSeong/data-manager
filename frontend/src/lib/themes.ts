// 테마 정의 + 적용 (themes/*.md 토큰 기반, index.css의 [data-theme]와 매칭)

export interface ThemeDef {
  id: string
  label: string
  /** 미리보기 스와치: [캔버스, 표면, 액센트, 텍스트] */
  swatch: [string, string, string, string]
}

export const THEMES: ThemeDef[] = [
  { id: 'default', label: '기본 다크', swatch: ['#09090b', '#27272a', '#3b82f6', '#e4e4e7'] },
  { id: 'tesla', label: 'Tesla', swatch: ['#000000', '#171717', '#e82127', '#ffffff'] },
  { id: 'sunset', label: 'Sunset', swatch: ['#1a1412', '#2b211d', '#ff7a59', '#fbeee6'] },
  { id: 'figma', label: 'Figma', swatch: ['#ffffff', '#f0f0f0', '#18a0fb', '#0d0d0d'] },
  { id: 'stripe', label: 'Stripe', swatch: ['#ffffff', '#eef1f6', '#635bff', '#0a0e27'] },
  { id: 'sage', label: 'Sage', swatch: ['#f6f8f4', '#e6ece1', '#2f7d4f', '#1f2a1c'] },
]

const STORAGE_KEY = 's3m.theme'

export function applyTheme(id: string): void {
  const root = document.documentElement
  if (id && id !== 'default') root.setAttribute('data-theme', id)
  else root.removeAttribute('data-theme')
  try { localStorage.setItem(STORAGE_KEY, id) } catch { /* ignore */ }
}

export function loadTheme(): string {
  try { return localStorage.getItem(STORAGE_KEY) || 'default' } catch { return 'default' }
}
