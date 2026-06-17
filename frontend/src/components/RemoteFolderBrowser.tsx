import { useEffect, useState } from 'react'
import { Folder, ArrowUp, RefreshCw, Home, ChevronRight } from 'lucide-react'
import * as api from '../lib/api'

interface RemoteFolderBrowserProps {
  /** 현재 선택된 디렉터리(제어 상태). 빈 문자열이면 홈으로 정규화된다. */
  value: string
  onChange: (path: string) => void
  /** 높이 클래스(기본 h-56) */
  heightClass?: string
}

/** 원격 디렉터리 폴더 브라우저 — breadcrumb + 하위 폴더 클릭으로 이동/선택. */
export function RemoteFolderBrowser({ value, onChange, heightClass = 'h-56' }: RemoteFolderBrowserProps) {
  const [folders, setFolders] = useState<{ key: string; name: string }[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setErr(null)
    api.getRemoteObjects(value || undefined)
      .then(res => {
        if (cancelled) return
        setFolders(res.folders.map(f => ({ key: f.key.replace(/\/$/, ''), name: f.name })))
        if (res.prefix && res.prefix !== value) onChange(res.prefix)
      })
      .catch(e => { if (!cancelled) setErr(e instanceof Error ? e.message : '경로를 열 수 없습니다') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [value]) // eslint-disable-line react-hooks/exhaustive-deps

  // breadcrumb 세그먼트 (누적 경로)
  const norm = value && value !== '/' ? value.replace(/\/+$/, '') : value
  const parts = norm && norm !== '/' ? norm.split('/').filter(Boolean) : []
  const crumbs = parts.map((seg, i) => ({ seg, path: '/' + parts.slice(0, i + 1).join('/') }))
  const parent = norm === '/' || !norm ? '/' : norm.replace(/\/[^/]+$/, '') || '/'

  return (
    <div className="border border-zinc-700 rounded-lg overflow-hidden">
      {/* breadcrumb 바 */}
      <div className="flex items-center gap-1 px-2 py-1.5 bg-zinc-800/60 border-b border-zinc-700 text-xs">
        <button
          onClick={() => onChange('/')}
          title="루트"
          className="p-0.5 text-zinc-500 hover:text-zinc-200 shrink-0"
        >
          <Home size={12} />
        </button>
        <button
          onClick={() => onChange(parent)}
          disabled={norm === '/' || !norm}
          title="상위 폴더"
          className="p-0.5 text-zinc-500 hover:text-zinc-200 disabled:opacity-30 shrink-0"
        >
          <ArrowUp size={12} />
        </button>
        <div className="flex items-center gap-0.5 min-w-0 overflow-x-auto whitespace-nowrap flex-1">
          {crumbs.length === 0 ? (
            <span className="text-zinc-400">/</span>
          ) : (
            crumbs.map((c, i) => (
              <span key={c.path} className="flex items-center gap-0.5">
                {i > 0 && <ChevronRight size={10} className="text-zinc-600" />}
                <button
                  onClick={() => onChange(c.path)}
                  className={`px-1 rounded hover:bg-zinc-700 ${i === crumbs.length - 1 ? 'text-zinc-100' : 'text-zinc-400'}`}
                >
                  {c.seg}
                </button>
              </span>
            ))
          )}
        </div>
        {loading && <RefreshCw size={11} className="animate-spin text-zinc-500 shrink-0" />}
      </div>

      {/* 하위 폴더 목록 */}
      <div className={`${heightClass} overflow-y-auto bg-zinc-900`}>
        {err ? (
          <div className="text-xs text-red-400 px-3 py-2">{err}</div>
        ) : folders.length === 0 ? (
          <div className="text-xs text-zinc-600 px-3 py-3 text-center">
            {loading ? '로드 중...' : '하위 폴더 없음'}
          </div>
        ) : (
          folders.map(f => (
            <button
              key={f.key}
              onClick={() => onChange(f.key)}
              className="w-full flex items-center gap-1.5 px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-800 text-left"
            >
              <Folder size={13} className="text-yellow-400 shrink-0" />
              <span className="truncate">{f.name}</span>
            </button>
          ))
        )}
      </div>

      {/* 선택된 경로 */}
      <div className="px-2 py-1.5 bg-zinc-800/60 border-t border-zinc-700">
        <span className="text-[11px] text-zinc-500">선택됨: </span>
        <span className="text-[11px] text-zinc-200 font-mono">{value || '/'}</span>
      </div>
    </div>
  )
}
