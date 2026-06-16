import { useState, useEffect, useCallback } from 'react'
import {
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  FolderOpen as FolderOpenIcon,
  Download,
  Upload,
  RefreshCw as SyncIcon,
  Ban,
} from 'lucide-react'
import * as api from '../lib/api'
import { useAppStore } from '../store/appStore'
import { formatBytes } from './ProgressBar'
import type { Job } from '../types'

const KIND_LABEL: Record<string, string> = {
  download: '다운로드',
  upload: '업로드',
  sync: '동기화',
  'remote-download': '원격 다운로드',
  'remote-upload': '원격 업로드',
}

const KIND_ICON: Record<string, React.ReactNode> = {
  download: <Download size={13} />,
  upload: <Upload size={13} />,
  sync: <SyncIcon size={13} />,
  'remote-download': <Download size={13} />,
  'remote-upload': <Upload size={13} />,
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'text-zinc-400',
  running: 'text-blue-400',
  done: 'text-emerald-400',
  error: 'text-red-400',
  canceled: 'text-zinc-500',
}

const STATUS_ICON: Record<string, React.ReactNode> = {
  pending: <Clock size={13} />,
  running: <Loader2 size={13} className="animate-spin" />,
  done: <CheckCircle2 size={13} />,
  error: <XCircle size={13} />,
  canceled: <Ban size={13} />,
}

const STATUS_LABEL: Record<string, string> = {
  pending: '대기',
  running: '진행 중',
  done: '완료',
  error: '오류',
  canceled: '취소됨',
}

function formatDate(iso: string | null): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function JobsPanel() {
  const { dispatch } = useAppStore()
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(false)

  const toast = (message: string, variant: 'error' | 'success' | 'info' = 'error') => {
    dispatch({ type: 'ADD_TOAST', payload: { id: Date.now().toString(), message, variant } })
  }

  const loadJobs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.getJobs()
      setJobs(res.jobs)
    } catch (e) {
      toast(e instanceof Error ? e.message : '작업 이력 로드 실패')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadJobs()
  }, [loadJobs])

  // 진행 중(pending/running) 잡이 있으면 주기적으로 새로고침
  useEffect(() => {
    const hasActive = jobs.some(j => j.status === 'running' || j.status === 'pending')
    if (!hasActive) return
    const id = setInterval(() => { void loadJobs() }, 1500)
    return () => clearInterval(id)
  }, [jobs, loadJobs])

  const handleCancel = async (jobId: string) => {
    try {
      await api.cancelJob(jobId)
      toast('취소를 요청했습니다.', 'info')
      await loadJobs()
    } catch (e) {
      toast(e instanceof Error ? e.message : '취소 실패')
    }
  }

  const handleReveal = async (job: Job) => {
    // 잡에 기록된 실제 로컬 경로를 Finder에서 연다.
    if (!job.localDir) {
      toast('열 수 있는 로컬 경로가 없습니다.')
      return
    }
    try {
      await api.revealInFinder(job.localDir)
      toast('Finder에서 열었습니다.', 'success')
    } catch {
      toast('경로 열기 실패')
    }
  }

  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-zinc-200">작업 이력</h3>
        <button
          onClick={loadJobs}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors px-2 py-1 rounded hover:bg-zinc-800"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          새로고침
        </button>
      </div>

      {jobs.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 text-zinc-600 text-xs gap-2">
          <Clock size={20} />
          {loading ? '로드 중...' : '작업 이력이 없습니다'}
        </div>
      ) : (
        <div className="space-y-2">
          {jobs.map(job => {
            const progress = job.totalBytes > 0 ? job.transferredBytes / job.totalBytes : 0

            return (
              <div
                key={job.jobId}
                className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-zinc-400">{KIND_ICON[job.kind]}</span>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-zinc-200">
                          {KIND_LABEL[job.kind]}
                        </span>
                        <span className={`flex items-center gap-1 text-xs ${STATUS_COLOR[job.status]}`}>
                          {STATUS_ICON[job.status]}
                          {STATUS_LABEL[job.status]}
                        </span>
                      </div>
                      <p className="text-[11px] text-zinc-600 font-mono truncate mt-0.5">
                        {job.jobId}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {(job.status === 'running' || job.status === 'pending') && (
                      <button
                        onClick={() => handleCancel(job.jobId)}
                        title="취소"
                        className="p-1 rounded text-zinc-500 hover:text-red-400 hover:bg-zinc-700 transition-colors"
                      >
                        <Ban size={13} />
                      </button>
                    )}
                    {(job.status === 'done' || job.status === 'error') && (
                      <button
                        onClick={() => handleReveal(job)}
                        title="Finder에서 열기"
                        className="p-1 rounded text-zinc-500 hover:text-zinc-300 hover:bg-zinc-700 transition-colors"
                      >
                        <FolderOpenIcon size={13} />
                      </button>
                    )}
                  </div>
                </div>

                {/* 통계 */}
                <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-zinc-500">
                  <div>
                    <span className="text-zinc-300">{job.completedFiles}</span>/{job.totalFiles}파일
                    {job.failedFiles > 0 && (
                      <span className="text-red-400 ml-1">({job.failedFiles}실패)</span>
                    )}
                  </div>
                  <div>{formatBytes(job.transferredBytes)}</div>
                  <div className="text-right">{formatDate(job.startedAt)}</div>
                </div>

                {/* 진행률 바 (running/done) */}
                {(job.status === 'running' || job.status === 'done') && job.totalBytes > 0 && (
                  <div className="mt-2 h-1 bg-zinc-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-500 rounded-full transition-all"
                      style={{ width: `${Math.round(progress * 100)}%` }}
                    />
                  </div>
                )}

                {/* 오류 메시지 */}
                {job.error && (
                  <p className="mt-1.5 text-[11px] text-red-400">{job.error}</p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
