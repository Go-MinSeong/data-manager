import { useState, useEffect } from 'react'
import { X, Check, Palette } from 'lucide-react'
import { THEMES, applyTheme, loadTheme } from '../lib/themes'
import * as api from '../lib/api'

interface SettingsPanelProps {
  onClose: () => void
}

export function SettingsPanel({ onClose }: SettingsPanelProps) {
  const [current, setCurrent] = useState(loadTheme())
  const [version, setVersion] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.getHealth()
      .then(r => { if (!cancelled) setVersion(r.version) })
      .catch(() => { /* 무시 */ })
    return () => { cancelled = true }
  }, [])

  const pick = (id: string) => {
    applyTheme(id)
    setCurrent(id)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl p-5"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
            <Palette size={15} /> 설정 · 테마
          </h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200">
            <X size={16} />
          </button>
        </div>

        <p className="text-xs text-zinc-500 mb-3">테마는 즉시 적용되고 다음 실행에도 유지됩니다.</p>

        <div className="grid grid-cols-2 gap-2">
          {THEMES.map(t => (
            <button
              key={t.id}
              onClick={() => pick(t.id)}
              className={`flex items-center gap-3 p-2.5 rounded-lg border transition-colors text-left ${
                current === t.id
                  ? 'border-blue-500 bg-zinc-800'
                  : 'border-zinc-700 hover:bg-zinc-800/60'
              }`}
            >
              {/* 스와치 */}
              <span className="flex items-center shrink-0 rounded-md overflow-hidden border border-zinc-700">
                {t.swatch.map((c, i) => (
                  <span key={i} style={{ background: c }} className="w-4 h-7 block" />
                ))}
              </span>
              <span className="flex-1 text-xs text-zinc-200">{t.label}</span>
              {current === t.id && <Check size={14} className="text-blue-400 shrink-0" />}
            </button>
          ))}
        </div>

        {/* 버전 */}
        <div className="mt-4 pt-3 border-t border-zinc-800 flex items-center justify-between text-xs text-zinc-500">
          <span>Data Manager</span>
          <span className="tabular-nums">{version ? `v${version}` : '—'}</span>
        </div>
      </div>
    </div>
  )
}
