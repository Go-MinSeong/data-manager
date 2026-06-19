import { useEffect, useRef } from 'react'

export interface MenuItem {
  label: string
  icon?: React.ReactNode
  onClick: () => void
  disabled?: boolean
}

interface ContextMenuProps {
  x: number
  y: number
  items: MenuItem[]
  onClose: () => void
}

/** 우클릭 컨텍스트 메뉴. 바깥 클릭·Esc·창 blur 시 닫힌다. */
export function ContextMenu({ x, y, items, onClose }: ContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onDocDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('mousedown', onDocDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('blur', onClose)
    return () => {
      document.removeEventListener('mousedown', onDocDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('blur', onClose)
    }
  }, [onClose])

  // 화면 밖으로 넘치지 않게 위치 보정
  const style: React.CSSProperties = {
    top: Math.min(y, window.innerHeight - items.length * 34 - 12),
    left: Math.min(x, window.innerWidth - 200),
  }

  return (
    <div
      ref={ref}
      style={style}
      className="fixed z-50 min-w-[170px] bg-zinc-900 border border-zinc-700 rounded-lg shadow-2xl py-1 text-xs"
    >
      {items.map((it, i) => (
        <button
          key={i}
          disabled={it.disabled}
          onClick={() => { it.onClick(); onClose() }}
          className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-zinc-300 hover:bg-zinc-800 disabled:text-zinc-600 disabled:hover:bg-transparent transition-colors"
        >
          {it.icon}
          {it.label}
        </button>
      ))}
    </div>
  )
}
