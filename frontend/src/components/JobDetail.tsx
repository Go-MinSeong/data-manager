import { useEffect } from 'react'
import { X, FolderOpen as FolderOpenIcon } from 'lucide-react'
import { formatBytes } from './ProgressBar'
import type { Job } from '../types'

interface JobDetailProps {
  job: Job
  kindLabel: string
  statusLabel: string
  statusColor: string
  onClose: () => void
  onReveal: (job: Job) => void
}

function fmt(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('ko-KR', {
    year: '2-digit', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function elapsed(a: string | null, b: string | null): string | null {
  if (!a || !b) return null
  const s = (new Date(b).getTime() - new Date(a).getTime()) / 1000
  if (s < 0) return null
  if (s < 60) return `${s.toFixed(1)}초`
  return `${Math.floor(s / 60)}분 ${Math.round(s % 60)}초`
}

export function JobDetail({ job, kindLabel, statusLabel, statusColor, onClose, onReveal }: JobDetailProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const took = elapsed(job.startedAt, job.finishedAt)
  const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-xs text-zinc-500 shrink-0">{label}</span>
      <span className="text-xs text-zinc-200 text-right break-all tabular-nums">{children}</span>
    </div>
  )

  return (
    <div className="dm-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-6" onClick={onClose}>
      <div
        className="dm-pop w-full max-w-md bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl p-5 max-h-[80vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-zinc-100">{kindLabel} 상세</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200"><X size={16} /></button>
        </div>

        <div className="divide-y divide-zinc-800">
          <Row label="상태"><span className={statusColor}>{statusLabel}</span></Row>
          <Row label="파일">
            {job.completedFiles}/{job.totalFiles}
            {job.failedFiles > 0 && <span className="text-red-400 ml-1">({job.failedFiles} 실패)</span>}
          </Row>
          <Row label="전송량">{formatBytes(job.transferredBytes)} / {formatBytes(job.totalBytes)}</Row>
          <Row label="시작">{fmt(job.startedAt)}</Row>
          <Row label="종료">{fmt(job.finishedAt)}</Row>
          {took && <Row label="소요">{took}</Row>}
          <Row label="작업 ID"><span className="font-mono text-[11px] text-zinc-400">{job.jobId}</span></Row>
          {job.localDir && (
            <div className="flex items-center justify-between gap-3 py-1.5">
              <span className="text-xs text-zinc-500 shrink-0">로컬 경로</span>
              <button
                onClick={() => onReveal(job)}
                className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 min-w-0"
              >
                <FolderOpenIcon size={12} className="shrink-0" />
                <span className="font-mono truncate">{job.localDir}</span>
              </button>
            </div>
          )}
        </div>

        {job.error && (
          <div className="mt-3 p-2.5 rounded-lg bg-red-950/50 border border-red-900 text-[11px] text-red-300 break-all">
            {job.error}
          </div>
        )}

        {job.failedItems && job.failedItems.length > 0 && (
          <div className="mt-3">
            <p className="text-xs text-zinc-400 mb-1.5">실패한 항목 ({job.failedItems.length})</p>
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {job.failedItems.map((f, i) => (
                <div key={i} className="text-[11px] bg-zinc-800/50 rounded px-2 py-1">
                  <div className="font-mono text-zinc-300 break-all">{f.key}</div>
                  <div className="text-red-400 break-all">{f.error}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
