import { useState, useEffect } from 'react'
import { FolderOpen, Download } from 'lucide-react'
import * as api from '../lib/api'
import { useJob } from '../hooks/useJob'
import { useAppStore } from '../store/appStore'
import { JobProgress } from './JobProgress'

interface RemoteDownloadPanelProps {
  checkedKeys: Set<string>
}

export function RemoteDownloadPanel({ checkedKeys }: RemoteDownloadPanelProps) {
  const { state, dispatch } = useAppStore()
  const [localDir, setLocalDir] = useState('')
  const [maxWorkers, setMaxWorkers] = useState(4)
  const [jobId, setJobId] = useState<string | null>(null)
  const { state: jobState, close: closeJob } = useJob(jobId)

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

    const dirs = [...checkedKeys].filter(k => k.endsWith('/'))
    const keys = [...checkedKeys].filter(k => !k.endsWith('/'))

    closeJob()
    setJobId(null)

    try {
      const res = await api.startRemoteDownload({
        remoteDir: dirs.length > 0 ? dirs[0].replace(/\/$/, '') : undefined,
        keys: keys.length > 0 ? keys : undefined,
        localDir,
        maxWorkers,
      })
      setJobId(res.jobId)
      toast('다운로드를 시작했습니다.', 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : '다운로드 시작 실패')
    }
  }

  const isRunning = jobId && !jobState.done && !jobState.error && !jobState.canceled
  const dirs = [...checkedKeys].filter(k => k.endsWith('/'))

  return (
    <div className="p-5 space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-zinc-200 mb-3">다운로드 (원격 → 로컬)</h3>

        {/* 선택된 항목 */}
        <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-3 mb-4">
          <span className="text-xs text-zinc-400 block mb-1">선택된 항목</span>
          {checkedKeys.size === 0 ? (
            <p className="text-xs text-zinc-600">왼쪽 트리에서 파일/폴더를 선택하세요</p>
          ) : (
            <div className="space-y-0.5">
              {[...checkedKeys].slice(0, 5).map(k => (
                <p key={k} className="text-xs text-zinc-300 font-mono truncate">{k}</p>
              ))}
              {checkedKeys.size > 5 && (
                <p className="text-xs text-zinc-500">... 외 {checkedKeys.size - 5}개</p>
              )}
            </div>
          )}
          {dirs.length > 1 && (
            <p className="mt-2 pt-2 border-t border-zinc-700 text-[11px] text-amber-400">
              폴더는 한 번에 하나만 받습니다. 첫 폴더({dirs[0]})만 처리됩니다.
            </p>
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

        {/* 동시 다운로드 수 */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs text-zinc-400">동시 다운로드 수</label>
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
          <div className="flex justify-between text-[10px] text-zinc-600 mt-0.5">
            <span>1</span><span>16</span>
          </div>
        </div>

        <button
          onClick={handleDownload}
          disabled={!!isRunning || !state.remoteConnection.connected || checkedKeys.size === 0}
          className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium py-2.5 rounded-lg transition-colors"
        >
          <Download size={15} />
          다운로드 시작
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
