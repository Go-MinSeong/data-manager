import { useState } from 'react'
import { FolderOpen, RefreshCw, ArrowDown, ArrowUp } from 'lucide-react'
import * as api from '../lib/api'
import { useJob } from '../hooks/useJob'
import { useAppStore } from '../store/appStore'
import { JobProgress } from './JobProgress'

export function SyncPanel() {
  const { state, dispatch } = useAppStore()
  const [direction, setDirection] = useState<'down' | 'up'>('down')
  const [prefix, setPrefix] = useState('')
  const [localDir, setLocalDir] = useState('')
  const [maxWorkers, setMaxWorkers] = useState(4)
  const [jobId, setJobId] = useState<string | null>(null)
  const { state: jobState, close: closeJob } = useJob(jobId)

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

  const handleSync = async () => {
    if (!state.selectedBucket) {
      toast('버킷을 선택하세요.')
      return
    }
    if (!localDir) {
      toast('로컬 경로를 입력하세요.')
      return
    }

    closeJob()
    setJobId(null)

    try {
      const res = await api.startSync({
        direction,
        bucket: state.selectedBucket,
        prefix,
        localDir,
        maxWorkers,
      })
      setJobId(res.jobId)
      toast('동기화를 시작했습니다.', 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : '동기화 시작 실패')
    }
  }

  const isRunning = jobId && !jobState.done && !jobState.error && !jobState.canceled

  return (
    <div className="p-5 space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-zinc-200 mb-3">동기화</h3>

        {/* 방향 선택 */}
        <div className="mb-4">
          <label className="text-xs text-zinc-400 mb-1 block">동기화 방향</label>
          <div className="flex gap-2">
            {(['down', 'up'] as const).map(d => (
              <button
                key={d}
                onClick={() => setDirection(d)}
                className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm border transition-colors ${
                  direction === d
                    ? 'bg-blue-600/20 border-blue-600 text-blue-300'
                    : 'bg-zinc-800 border-zinc-700 text-zinc-400 hover:text-zinc-200'
                }`}
              >
                {d === 'down' ? <ArrowDown size={14} /> : <ArrowUp size={14} />}
                {d === 'down' ? 'S3 → 로컬' : '로컬 → S3'}
              </button>
            ))}
          </div>
        </div>

        {/* 대상 버킷 */}
        <div className="mb-4">
          <label className="text-xs text-zinc-400 mb-1 block">버킷</label>
          <div className="px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm text-zinc-300">
            {state.selectedBucket ?? <span className="text-zinc-600">왼쪽 트리에서 버킷을 선택하세요</span>}
          </div>
        </div>

        {/* Prefix */}
        <div className="mb-4">
          <label className="text-xs text-zinc-400 mb-1 block">S3 Prefix</label>
          <input
            value={prefix}
            onChange={e => setPrefix(e.target.value)}
            placeholder="data/images/"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
          />
        </div>

        {/* 로컬 경로 */}
        <div className="mb-4">
          <label className="text-xs text-zinc-400 mb-1 block">로컬 경로</label>
          <div className="flex gap-2">
            <input
              value={localDir}
              onChange={e => setLocalDir(e.target.value)}
              placeholder="/Users/me/data"
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
            />
            <button
              onClick={handlePickFolder}
              className="px-3 py-2 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 rounded-lg text-zinc-400 hover:text-zinc-200 transition-colors"
            >
              <FolderOpen size={15} />
            </button>
          </div>
        </div>

        {/* 옵션 */}
        <div className="mb-4 space-y-3">
          <div className="flex items-start gap-2 text-[11px] text-zinc-500 bg-zinc-800/50 border border-zinc-700/60 rounded-lg px-3 py-2">
            <span>🛡️</span>
            <span>이 도구는 <b className="text-zinc-300">변경분만 복사</b>합니다. S3 객체나 로컬 파일을 <b className="text-zinc-300">삭제하지 않습니다.</b></span>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-zinc-400">동시 전송 수</label>
              <span className="text-xs text-zinc-200 font-medium">{maxWorkers}</span>
            </div>
            <input
              type="range"
              min={1}
              max={16}
              value={maxWorkers}
              onChange={e => setMaxWorkers(Number(e.target.value))}
              className="w-full accent-blue-500"
            />
          </div>
        </div>

        {/* 동기화 버튼 */}
        <button
          onClick={handleSync}
          disabled={!!isRunning || !state.selectedBucket}
          className="w-full flex items-center justify-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium py-2.5 rounded-lg transition-colors"
        >
          <RefreshCw size={15} />
          동기화 시작
        </button>
      </div>

      {/* 진행률 */}
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
