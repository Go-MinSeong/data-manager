import { useState, useEffect } from 'react'
import { FilePlus, Upload, X, Gauge, FolderPlus } from 'lucide-react'
import * as api from '../lib/api'
import { useJob } from '../hooks/useJob'
import { useSubmitGuard } from '../hooks/useSubmitGuard'
import { useAppStore } from '../store/appStore'
import { JobProgress } from './JobProgress'
import { formatSpeed } from './ProgressBar'

interface RemoteUploadPanelProps {
  selectedDir?: string
  /** 트리에서 "업로드 위치로 설정"하면 대상 경로를 강제로 채운다(nonce 변할 때). */
  preset?: { dir: string; nonce: number }
  /** 드래그-드롭으로 들어온 파일 경로(nonce 변할 때 추가). */
  filesPreset?: { paths: string[]; nonce: number }
}

export function RemoteUploadPanel({ selectedDir, preset, filesPreset }: RemoteUploadPanelProps) {
  const { state, dispatch } = useAppStore()
  const [remoteDir, setRemoteDir] = useState('')
  const [touched, setTouched] = useState(false)
  const [showNewFolder, setShowNewFolder] = useState(false)
  const [folderName, setFolderName] = useState('')
  const [localPaths, setLocalPaths] = useState<string[]>([])

  // 드래그-드롭으로 들어온 파일을 목록에 추가(중복 제거)
  useEffect(() => {
    if (filesPreset && filesPreset.nonce > 0 && filesPreset.paths.length) {
      setLocalPaths(prev => [...new Set([...prev, ...filesPreset.paths])])
    }
  }, [filesPreset?.nonce]) // eslint-disable-line react-hooks/exhaustive-deps
  const [maxWorkers, setMaxWorkers] = useState(4)
  const jobId = state.activeJobs['remote-upload'] ?? null
  const setJobId = (id: string | null) =>
    dispatch({ type: 'SET_ACTIVE_JOB', payload: { key: 'remote-upload', id } })
  const { state: jobState, close: closeJob } = useJob(jobId)
  const { submitting, run } = useSubmitGuard()

  // 사용자가 직접 수정하기 전에는 트리에서 선택한 디렉터리를 대상 경로로 따라간다.
  useEffect(() => {
    if (!touched && selectedDir) setRemoteDir(selectedDir)
  }, [selectedDir, touched])

  // 트리에서 "업로드 위치로 설정"하면 사용자 편집 여부와 무관하게 강제로 채운다.
  useEffect(() => {
    if (preset && preset.nonce > 0) { setRemoteDir(preset.dir); setTouched(true) }
  }, [preset?.nonce]) // eslint-disable-line react-hooks/exhaustive-deps

  const [measuring, setMeasuring] = useState(false)
  const [speed, setSpeed] = useState<{ up: number; down: number } | null>(null)

  const toast = (message: string, variant: 'error' | 'success' | 'info' = 'error') => {
    dispatch({ type: 'ADD_TOAST', payload: { id: Date.now().toString(), message, variant } })
  }

  const handleMeasure = async () => {
    setMeasuring(true); setSpeed(null)
    try {
      const r = await api.measureRemote(remoteDir || undefined)
      setSpeed({ up: r.uploadBps, down: r.downloadBps })
    } catch (e) {
      toast(e instanceof Error ? e.message : '속도 측정 실패')
    } finally { setMeasuring(false) }
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

  const handlePickFiles = async () => {
    try {
      const res = await api.pickFiles()
      if (res.paths.length > 0) {
        setLocalPaths(prev => [...new Set([...prev, ...res.paths])])
      }
    } catch {
      toast('파일 선택 실패 (네이티브 앱에서 지원)')
    }
  }

  const removePath = (path: string) => {
    setLocalPaths(prev => prev.filter(p => p !== path))
  }

  const handleCreateFolder = async () => {
    if (!state.remoteConnection.connected) { toast('원격 서버에 연결하세요.'); return }
    if (!remoteDir) { toast('대상 원격 경로를 먼저 지정하세요.'); return }
    const name = folderName.trim().replace(/^\/+|\/+$/g, '')
    if (!name) { toast('폴더 이름을 입력하세요.'); return }
    const path = `${remoteDir.replace(/\/$/, '')}/${name}`
    try {
      await api.createRemoteFolder(path)
      setRemoteDir(path)
      setTouched(true)
      setFolderName('')
      setShowNewFolder(false)
      toast(`폴더를 생성했습니다: ${path}`, 'success')
    } catch (e) {
      if (api.isDisconnectError(e)) {
        dispatch({ type: 'SET_REMOTE_CONNECTION', payload: { connected: false } })
        toast('원격 연결이 끊겼습니다. 다시 연결하세요.')
        return
      }
      toast(e instanceof Error ? e.message : '폴더 생성 실패')
    }
  }

  const handleUpload = async () => {
    if (!state.remoteConnection.connected) {
      toast('원격 서버에 연결하세요.')
      return
    }
    if (!remoteDir) {
      toast('대상 원격 경로를 입력하세요.')
      return
    }
    if (localPaths.length === 0) {
      toast('업로드할 파일/폴더를 선택하세요.')
      return
    }

    closeJob()
    setJobId(null)

    try {
      const res = await api.startRemoteUpload({ remoteDir, localPaths, maxWorkers })
      setJobId(res.jobId)
      toast('업로드를 시작했습니다.', 'success')
    } catch (e) {
      if (api.isDisconnectError(e)) {
        dispatch({ type: 'SET_REMOTE_CONNECTION', payload: { connected: false } })
        toast('원격 연결이 끊겼습니다. 다시 연결하세요.')
        return
      }
      toast(e instanceof Error ? e.message : '업로드 시작 실패')
    }
  }

  const isRunning = jobId && !jobState.done && !jobState.error && !jobState.canceled

  return (
    <div className="p-5 space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-zinc-200 mb-3">업로드 (로컬 → 원격)</h3>

        {/* 대상 원격 경로 */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs text-zinc-400">대상 원격 경로</label>
            <button
              onClick={() => setShowNewFolder(v => !v)}
              disabled={!remoteDir}
              className="flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300 disabled:text-zinc-600"
            >
              <FolderPlus size={11} />
              새 폴더
            </button>
          </div>
          <input
            value={remoteDir}
            onChange={e => { setRemoteDir(e.target.value); setTouched(true) }}
            placeholder="/home/ubuntu/uploads"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
          />
          {showNewFolder && (
            <div className="flex gap-1.5 mt-2">
              <input
                value={folderName}
                onChange={e => setFolderName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') void handleCreateFolder() }}
                placeholder="새 폴더 이름"
                autoFocus
                className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-xs text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
              />
              <button
                onClick={() => void handleCreateFolder()}
                className="px-2.5 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs rounded-lg transition-colors"
              >
                생성
              </button>
            </div>
          )}
          <p className="text-[11px] text-zinc-600 mt-1">왼쪽 트리에서 폴더를 펼치면 자동으로 채워집니다.</p>
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
              <p className="text-xs text-zinc-600 text-center py-4">파일/폴더를 선택하거나 끌어다 놓으세요</p>
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

        <button
          onClick={() => run(handleUpload)}
          disabled={!!isRunning || submitting || !state.remoteConnection.connected || localPaths.length === 0}
          className="w-full flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium py-2.5 rounded-lg transition-colors"
        >
          <Upload size={15} />
          {submitting ? '시작 중...' : '업로드 시작'}
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
