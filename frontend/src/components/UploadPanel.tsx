import { useState } from 'react'
import { FilePlus, Upload, X } from 'lucide-react'
import * as api from '../lib/api'
import { useJob } from '../hooks/useJob'
import { useSubmitGuard } from '../hooks/useSubmitGuard'
import { useAppStore } from '../store/appStore'
import { JobProgress } from './JobProgress'

export function UploadPanel() {
  const { state, dispatch } = useAppStore()
  const [prefix, setPrefix] = useState('')
  const [localPaths, setLocalPaths] = useState<string[]>([])
  const [maxWorkers, setMaxWorkers] = useState(4)
  const jobId = state.activeJobs['upload'] ?? null
  const setJobId = (id: string | null) =>
    dispatch({ type: 'SET_ACTIVE_JOB', payload: { key: 'upload', id } })
  const { state: jobState, close: closeJob } = useJob(jobId)
  const { submitting, run } = useSubmitGuard()

  const toast = (message: string, variant: 'error' | 'success' | 'info' = 'error') => {
    dispatch({ type: 'ADD_TOAST', payload: { id: Date.now().toString(), message, variant } })
  }

  const handlePickFiles = async () => {
    try {
      const res = await api.pickFiles()
      if (res.paths.length > 0) {
        setLocalPaths(prev => {
          const combined = [...prev, ...res.paths]
          // 중복 제거
          return [...new Set(combined)]
        })
      }
    } catch {
      toast('파일 선택 실패 (네이티브 앱에서 지원)')
    }
  }

  const removePath = (path: string) => {
    setLocalPaths(prev => prev.filter(p => p !== path))
  }

  const handleRecommend = async () => {
    if (localPaths.length === 0) { toast('업로드할 파일을 먼저 선택하세요.'); return }
    try {
      const r = await api.getLocalFlat(localPaths)
      setMaxWorkers(api.recommendWorkers(r.totalFiles, r.totalBytes))
      toast('파일 수·크기에 맞춰 동시 수를 추천했습니다.', 'info')
    } catch (e) {
      toast(e instanceof Error ? e.message : '추천 계산 실패')
    }
  }

  const handleUpload = async () => {
    if (!state.selectedBucket) {
      toast('버킷을 선택하세요.')
      return
    }
    if (localPaths.length === 0) {
      toast('업로드할 파일/폴더를 선택하세요.')
      return
    }

    closeJob()
    setJobId(null)

    try {
      const res = await api.startUpload({
        bucket: state.selectedBucket,
        prefix,
        localPaths,
        maxWorkers,
      })
      setJobId(res.jobId)
      toast('업로드를 시작했습니다.', 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : '업로드 시작 실패')
    }
  }

  const isRunning = jobId && !jobState.done && !jobState.error && !jobState.canceled

  return (
    <div className="p-5 space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-zinc-200 mb-3">업로드</h3>

        {/* 대상 버킷/Prefix */}
        <div className="mb-4">
          <label className="text-xs text-zinc-400 mb-1 block">대상 버킷</label>
          <div className="px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm text-zinc-300">
            {state.selectedBucket ?? <span className="text-zinc-600">왼쪽 트리에서 버킷을 선택하세요</span>}
          </div>
        </div>

        <div className="mb-4">
          <label className="text-xs text-zinc-400 mb-1 block">대상 Prefix (선택)</label>
          <input
            value={prefix}
            onChange={e => setPrefix(e.target.value)}
            placeholder="uploads/2024/"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
          />
        </div>

        {/* 파일/폴더 선택 */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs text-zinc-400">업로드할 파일/폴더</label>
            <button
              onClick={handlePickFiles}
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1"
            >
              <FilePlus size={11} />
              선택
            </button>
          </div>
          <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg min-h-16 p-2">
            {localPaths.length === 0 ? (
              <p className="text-xs text-zinc-600 text-center py-4">파일/폴더를 선택하세요</p>
            ) : (
              <div className="space-y-1">
                {localPaths.map(p => (
                  <div key={p} className="flex items-center gap-2 text-xs">
                    <span className="flex-1 text-zinc-300 font-mono truncate">{p}</span>
                    <button
                      onClick={() => removePath(p)}
                      className="text-zinc-600 hover:text-red-400 transition-colors shrink-0"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 동시 업로드 수 */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs text-zinc-400">동시 업로드 수</label>
            <div className="flex items-center gap-2">
              <button
                onClick={handleRecommend}
                disabled={localPaths.length === 0}
                className="text-[11px] text-blue-400 hover:text-blue-300 disabled:text-zinc-600"
              >
                추천
              </button>
              <span className="text-xs text-zinc-200 font-medium">{maxWorkers}</span>
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
        </div>

        {/* 업로드 버튼 */}
        <button
          onClick={() => run(handleUpload)}
          disabled={!!isRunning || submitting || !state.selectedBucket || localPaths.length === 0}
          className="w-full flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium py-2.5 rounded-lg transition-colors"
        >
          <Upload size={15} />
          {submitting ? '시작 중...' : '업로드 시작'}
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
