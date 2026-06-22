import { useEffect, useState } from 'react'
import { X } from 'lucide-react'

export function isImagePath(name: string): boolean {
  return /\.(png|jpe?g|gif|webp|bmp|svg|avif|ico)$/i.test(name)
}

interface ImagePreviewProps {
  src: string
  title: string
  onClose: () => void
}

/** 전체 화면 오버레이 이미지 미리보기. 바깥 클릭·Esc로 닫는다. */
export function ImagePreview({ src, title, onClose }: ImagePreviewProps) {
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    setFailed(false)
  }, [src])

  return (
    <div
      onClick={onClose}
      className="dm-overlay fixed inset-0 z-[60] bg-black/75 flex items-center justify-center p-8"
    >
      <div onClick={e => e.stopPropagation()} className="dm-pop flex flex-col items-center gap-2 max-w-full max-h-full">
        {failed ? (
          <div className="max-w-full max-h-[80vh] min-w-72 rounded-lg border border-red-500/30 bg-zinc-950 px-6 py-5 text-sm text-red-200 shadow-2xl">
            이미지를 불러오지 못했습니다.
          </div>
        ) : (
          <img
            src={src}
            alt={title}
            onError={() => setFailed(true)}
            className="max-w-full max-h-[80vh] object-contain rounded-lg shadow-2xl outline outline-1 -outline-offset-1 outline-white/10"
          />
        )}
        <div className="flex items-center gap-2 text-xs text-zinc-300">
          <span className="font-mono truncate max-w-md">{title}</span>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-100" title="닫기 (Esc)">
            <X size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}
