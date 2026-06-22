import { useState, useEffect } from 'react'
import { FolderOpen, Download, Gauge, X } from 'lucide-react'
import * as api from '../lib/api'
import { useJob } from '../hooks/useJob'
import { useSubmitGuard } from '../hooks/useSubmitGuard'
import { useAppStore } from '../store/appStore'
import { JobProgress } from './JobProgress'
import { formatSpeed } from './ProgressBar'

interface RemoteDownloadPanelProps {
  checkedKeys: Set<string>
  onCheckedChange?: (keys: Set<string>) => void
}

export function RemoteDownloadPanel({ checkedKeys, onCheckedChange }: RemoteDownloadPanelProps) {
  const { state, dispatch } = useAppStore()
  const removeKey = (k: string) => {
    const next = new Set(checkedKeys)
    next.delete(k)
    onCheckedChange?.(next)
  }
  const [localDir, setLocalDir] = useState('')
  const [maxWorkers, setMaxWorkers] = useState(4)
  const [measuring, setMeasuring] = useState(false)
  const [speed, setSpeed] = useState<{ up: number; down: number } | null>(null)
  const jobId = state.activeJobs['remote-download'] ?? null
  const setJobId = (id: string | null) =>
    dispatch({ type: 'SET_ACTIVE_JOB', payload: { key: 'remote-download', id } })
  const { state: jobState, close: closeJob } = useJob(jobId)
  const { submitting, run } = useSubmitGuard()

  const handleMeasure = async () => {
    setMeasuring(true); setSpeed(null)
    try {
      const r = await api.measureRemote()
      setSpeed({ up: r.uploadBps, down: r.downloadBps })
    } catch (e) {
      dispatch({ type: 'ADD_TOAST', payload: { id: Date.now().toString(), message: e instanceof Error ? e.message : '속도 측정 실패', variant: 'error' } })
    } finally { setMeasuring(false) }
  }

  const handleRecommend = async () => {
    if (checkedKeys.size === 0) return
    try {
      let tf = 0, tb = 0
      const dirs = [...checkedKeys].filter(k => k.endsWith('/'))
      tf = [...checkedKeys].filter(k => !k.endsWith('/')).length
      for (const d of dirs) {
        const r = await api.getRemoteFlat(d.replace(/\/$/, ''))
        tf += r.totalFiles; tb += r.totalBytes
      }
      setMaxWorkers(api.recommendWorkers(tf, tb))
    } catch { /* 무시 */ }
  }

  useEffect(() => {
    api.getPreferences()
      .then(p => {
        if (p.lastDownloadDir) setLocalDir(prev => prev || p.lastDownloadDir)
      })
      .catch(() => { /* 무시 */ })
  }, [])

  const toast = (message: string, variant: 'error' | 'success' | 'info' = 'error') => {
    dispatch({ type: 'ADD_TOAST', payload: { id: Date.now().toString(), message, variant } })
  }

  const handlePickFolder = async () => {
    try {
      const res = await api.pickFolder()
      if (res.path) setLocalDir(res.path)
    } catch {
      toast('폴더 선택 실패 (네이티브 앱에서 지원)')
    }
  }

  const handleDownload = async () => {
    if (!state.remoteConnection.connected) {
      toast('원격 서버에 연결하세요.')
      return
    }
    if (!localDir) {
      toast('저장 경로를 입력하세요.')
      return
    }
    if (checkedKeys.size === 0) {
      toast('다운로드할 항목을 선택하세요.')
      return
    }

    const dirs = [...checkedKeys].filter(k => k.endsWith('/')).map(d => d.replace(/\/$/, ''))
    const keys = [...checkedKeys].filter(k => !k.endsWith('/'))

    closeJob()
    setJobId(null)

    try {
      const res = await api.startRemoteDownload({
        remoteDirs: dirs.length > 0 ? dirs : undefined,
        keys: keys.length > 0 ? keys : undefined,
        localDir,
        maxWorkers,
      })
      setJobId(res.jobId)
      toast('다운로드를 시작했습니다.', 'success')
    } catch (e) {
      if (api.isDisconnectError(e)) {
        dispatch({ type: 'SET_REMOTE_CONNECTION', payload: { connected: false } })
        toast('원격 연결이 끊겼습니다. 다시 연결하세요.')
        return
      }
      toast(e instanceof Error ? e.message : '다운로드 시작 실패')
    }
  }

  const isRunning = jobId && !jobState.done && !jobState.error && !jobState.canceled

  return (
    <div className="p-5 space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-zinc-200 mb-3">다운로드 (원격 → 로컬)</h3>

        {/* 선택된 항목 */}
        <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-3 mb-4">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-zinc-400">선택된 항목 ({checkedKeys.size})</span>
            {checkedKeys.size > 0 && onCheckedChange && (
              <button
                onClick={() => onCheckedChange(new Set())}
                className="text-xs text-zinc-500 hover:text-red-400 transition-colors"
              >
                전체 해제
              </button>
            )}
          </div>
          {checkedKeys.size === 0 ? (
            <p className="text-xs text-zinc-600">왼쪽 트리에서 파일/폴더를 선택하세요</p>
          ) : (
            <div className="space-y-0.5 max-h-40 overflow-y-auto">
              {[...checkedKeys].map(k => (
                <div key={k} className="flex items-center gap-2 text-xs">
                  <span className="flex-1 text-zinc-300 font-mono truncate">{k}</span>
                  <button
                    onClick={() => removeKey(k)}
                    title="목록에서 제거"
                    className="text-zinc-600 hover:text-red-400 transition-colors shrink-0"
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 저장 경로 */}
        <div className="mb-4">
          <label className="text-xs text-zinc-400 mb-1 block">저장 경로</label>
          <div className="flex gap-2">
            <input
              value={localDir}
              onChange={e => setLocalDir(e.target.value)}
              placeholder="/Users/me/Downloads"
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
            />
            <button
              onClick={handlePickFolder}
              className="px-3 py-2 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 rounded-lg text-zinc-400 hover:text-zinc-200 transition-colors"
              title="폴더 선택"
            >
              <FolderOpen size={15} />
            </button>
          </div>
        </div>

        {/* 링크 속도 측정 (Mac ↔ 원격) */}
        <div className="flex items-center gap-3 mb-4">
          <button
            onClick={handleMeasure}
            disabled={measuring}
            className="flex items-center gap-1.5 text-xs text-zinc-300 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 px-2.5 py-1.5 rounded-lg transition-colors"
          >
            <Gauge size={13} className={measuring ? 'animate-pulse' : ''} />
            {measuring ? '측정 중...' : '링크 속도 측정'}
          </button>
          {speed && (
            <span className="text-[11px] text-zinc-400">
              ↑ {formatSpeed(speed.up)} · ↓ {formatSpeed(speed.down)}
            </span>
          )}
        </div>

        {/* 동시 다운로드 수 */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs text-zinc-400">동시 다운로드 수</label>
            <div className="flex items-center gap-2">
              <button
                onClick={handleRecommend}
                disabled={checkedKeys.size === 0}
                className="text-[11px] text-blue-400 hover:text-blue-300 disabled:text-zinc-600"
              >
                추천
              </button>
              <span className="text-xs text-zinc-200 font-medium tabular-nums">{maxWorkers}</span>
            </div>
          </div>
          <input
            type="range"
            min={1}
            max={16}
            value={maxWorkers}
            onChange={e => setMaxWorkers(Number(e.target.value))}
            className="w-full accent-blue-500"
          />
          <div className="flex justify-between text-[10px] text-zinc-600 mt-0.5">
            <span>1</span><span>16</span>
          </div>
        </div>

        <button
          onClick={() => run(handleDownload)}
          disabled={!!isRunning || submitting || !state.remoteConnection.connected || checkedKeys.size === 0}
          className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium py-2.5 rounded-lg transition-[background-color,scale] duration-150 active:scale-[0.96]"
        >
          <Download size={15} />
          {submitting ? '시작 중...' : '다운로드 시작'}
        </button>
      </div>

      {jobId && (
        <JobProgress
          jobId={jobId}
          jobState={jobState}
          onDismiss={() => { setJobId(null); closeJob() }}
        />
      )}
    </div>
  )
}
