import { X, CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import { ProgressBar, formatBytes, formatSpeed, formatEta } from './ProgressBar'
import { cancelJob } from '../lib/api'
import type { UseJobState } from '../hooks/useJob'

interface JobProgressProps {
  jobId: string | null
  jobState: UseJobState
  onDismiss?: () => void
}

export function JobProgress({ jobId, jobState, onDismiss }: JobProgressProps) {
  const { progress, done, error, canceled, job } = jobState

  if (!jobId) return null

  // 완료 후 평균 속도 (직통 전송 등 실시간 속도가 없는 경우의 지표)
  const doneBytes = progress?.transferredBytes ?? job?.transferredBytes ?? 0
  const avgBps = done && done.elapsedSec > 0 ? doneBytes / done.elapsedSec : 0

  const handleCancel = async () => {
    if (!jobId) return
    try {
      await cancelJob(jobId)
    } catch {
      // ignore
    }
  }

  // 완료
  if (done) {
    return (
      <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-4">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} className="text-emerald-400 shrink-0" />
            <div>
              <p className="text-sm font-medium text-zinc-200">전송 완료</p>
              <p className="text-xs text-zinc-400 mt-0.5">
                성공 {done.success}건 / 실패 {done.failure}건 · {done.elapsedSec.toFixed(1)}초
                {avgBps > 0 && <> · 평균 {formatSpeed(avgBps)}</>}
              </p>
            </div>
          </div>
          {onDismiss && (
            <button onClick={onDismiss} className="text-zinc-500 hover:text-zinc-300 transition-colors">
              <X size={14} />
            </button>
          )}
        </div>
      </div>
    )
  }

  // 오류
  if (error) {
    return (
      <div className="bg-red-950/50 border border-red-800 rounded-lg p-4">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <XCircle size={16} className="text-red-400 shrink-0" />
            <div>
              <p className="text-sm font-medium text-red-200">오류 발생</p>
              <p className="text-xs text-red-400 mt-0.5">{error}</p>
            </div>
          </div>
          {onDismiss && (
            <button onClick={onDismiss} className="text-red-500 hover:text-red-300 transition-colors">
              <X size={14} />
            </button>
          )}
        </div>
      </div>
    )
  }

  // 취소됨
  if (canceled) {
    return (
      <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-zinc-400">취소됨</span>
          {onDismiss && (
            <button onClick={onDismiss} className="text-zinc-500 hover:text-zinc-300 transition-colors">
              <X size={14} />
            </button>
          )}
        </div>
      </div>
    )
  }

  // 진행 중
  const pct = progress && progress.totalBytes > 0
    ? progress.transferredBytes / progress.totalBytes
    : 0

  return (
    <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Loader2 size={14} className="animate-spin text-blue-400 shrink-0" />
          <span className="text-sm font-medium text-zinc-200">전송 중...</span>
        </div>
        <button
          onClick={handleCancel}
          className="text-xs text-zinc-500 hover:text-red-400 transition-colors flex items-center gap-1"
        >
          <X size={12} />
          취소
        </button>
      </div>

      {progress && (
        <>
          <ProgressBar value={pct} />
          <div className="grid grid-cols-2 gap-2 text-xs text-zinc-400">
            <div>
              <span className="text-zinc-200">{progress.completedFiles}</span>
              {' / '}
              <span>{progress.totalFiles}개</span>
            </div>
            <div className="text-right">
              <span className="text-zinc-200">{formatBytes(progress.transferredBytes)}</span>
              {' / '}
              <span>{formatBytes(progress.totalBytes)}</span>
            </div>
            <div className="text-zinc-500 text-[11px] truncate" title={progress.currentFile}>
              {progress.currentFile}
            </div>
            <div className="text-right space-x-2">
              <span>{formatSpeed(progress.speedBps)}</span>
              <span className="text-zinc-500">ETA {formatEta(progress.etaSec)}</span>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
