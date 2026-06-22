import { useState, useEffect } from 'react'
import { FolderOpen, Download, Info, X } from 'lucide-react'
import * as api from '../lib/api'
import { useJob } from '../hooks/useJob'
import { useSubmitGuard } from '../hooks/useSubmitGuard'
import { useAppStore } from '../store/appStore'
import { JobProgress } from './JobProgress'
import { formatBytes } from './ProgressBar'

interface DownloadPanelProps {
  checkedKeys: Set<string>
  onCheckedChange?: (keys: Set<string>) => void
}

export function DownloadPanel({ checkedKeys, onCheckedChange }: DownloadPanelProps) {
  const { state, dispatch } = useAppStore()
  const removeKey = (k: string) => {
    const next = new Set(checkedKeys)
    next.delete(k)
    onCheckedChange?.(next)
  }
  const [localDir, setLocalDir] = useState('')
  const [maxWorkers, setMaxWorkers] = useState(4)
  const [pathInput, setPathInput] = useState('')
  const jobId = state.activeJobs['download'] ?? null
  const setJobId = (id: string | null) =>
    dispatch({ type: 'SET_ACTIVE_JOB', payload: { key: 'download', id } })
  const [preview, setPreview] = useState<{ totalFiles: number; totalBytes: number } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [freeSpace, setFreeSpace] = useState<number | null>(null)
  const { state: jobState, close: closeJob } = useJob(jobId)
  const { submitting, run } = useSubmitGuard()

  // 저장 경로의 디스크 여유 공간 조회
  useEffect(() => {
    if (!localDir) { setFreeSpace(null); return }
    let cancelled = false
    api.getLocalDiskSpace(localDir)
      .then(r => { if (!cancelled) setFreeSpace(r.free) })
      .catch(() => { if (!cancelled) setFreeSpace(null) })
    return () => { cancelled = true }
  }, [localDir])

  // 마지막으로 사용한 다운로드 경로를 기본값으로 채운다 (없으면 ~/Downloads).
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

  // s3://버킷/키 또는 (현재 버킷의) 키/prefix를 직접 입력해 선택에 추가
  const addByPath = () => {
    const raw = pathInput.trim()
    if (!raw) return
    let bucket = state.selectedBucket
    let key = raw
    const m = raw.match(/^s3:\/\/([^/]+)\/?(.*)$/i)
    if (m) {
      bucket = m[1]
      key = m[2]
    }
    if (!bucket) { toast('버킷을 선택하거나 s3://버킷/키 형식으로 입력하세요.'); return }
    if (!key) { toast('키(경로)를 입력하세요.'); return }
    if (bucket !== state.selectedBucket) {
      // 다른 버킷이면 전환하고 기존 선택은 초기화(단일 버킷 다운로드)
      dispatch({ type: 'SET_BUCKET', payload: bucket })
      onCheckedChange?.(new Set([key]))
      toast(`버킷 전환: ${bucket}`, 'info')
    } else {
      const next = new Set(checkedKeys)
      next.add(key)
      onCheckedChange?.(next)
    }
    setPathInput('')
  }

  const handlePickFolder = async () => {
    try {
      const res = await api.pickFolder()
      if (res.path) setLocalDir(res.path)
    } catch {
      toast('폴더 선택 실패 (네이티브 앱에서 지원)')
    }
  }

  const handlePreview = async () => {
    if (!state.selectedBucket || checkedKeys.size === 0) {
      toast('버킷과 다운로드 대상을 선택하세요.')
      return
    }
    setPreviewLoading(true)
    try {
      // 선택된 모든 폴더의 크기를 합산하고, 파일은 개수만 더한다.
      const prefixes = [...checkedKeys].filter(k => k.endsWith('/'))
      const keys = [...checkedKeys].filter(k => !k.endsWith('/'))
      let totalFiles = keys.length
      let totalBytes = 0
      for (const p of prefixes) {
        const r = await api.getFlatObjects(state.selectedBucket, p)
        totalFiles += r.totalFiles
        totalBytes += r.totalBytes
      }
      setPreview({ totalFiles, totalBytes })
      return { totalFiles, totalBytes }
    } catch (e) {
      toast(e instanceof Error ? e.message : '미리보기 실패')
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleRecommend = async () => {
    const s = preview ?? (await handlePreview())
    if (!s) return
    setMaxWorkers(api.recommendWorkers(s.totalFiles, s.totalBytes))
    toast('파일 수·크기에 맞춰 동시 수를 추천했습니다.', 'info')
  }

  const handleDownload = async () => {
    if (!state.selectedBucket) {
      toast('버킷을 선택하세요.')
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

    // 체크된 폴더(prefix) / 파일(keys) 분리 — 전부 전송
    const prefixes = [...checkedKeys].filter(k => k.endsWith('/'))
    const keys = [...checkedKeys].filter(k => !k.endsWith('/'))

    closeJob()
    setJobId(null)

    try {
      const res = await api.startDownload({
        bucket: state.selectedBucket,
        prefixes: prefixes.length > 0 ? prefixes : undefined,
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

  return (
    <div className="p-5 space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-zinc-200 mb-3">다운로드</h3>

        {/* 선택된 항목 */}
        <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-3 mb-4">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-zinc-400">선택된 항목 ({checkedKeys.size})</span>
            <div className="flex items-center gap-2">
              {checkedKeys.size > 0 && onCheckedChange && (
                <button
                  onClick={() => onCheckedChange(new Set())}
                  className="text-xs text-zinc-500 hover:text-red-400 transition-colors"
                >
                  전체 해제
                </button>
              )}
              <button
                onClick={handlePreview}
                disabled={previewLoading || checkedKeys.size === 0 || !state.selectedBucket}
                className="text-xs text-blue-400 hover:text-blue-300 disabled:text-zinc-600 transition-colors flex items-center gap-1"
              >
                <Info size={11} />
                {previewLoading ? '계산 중...' : '크기 확인'}
              </button>
            </div>
          </div>
          {/* 경로 직접 입력 (s3://버킷/키 붙여넣기) */}
          <div className="flex gap-1.5 mb-2">
            <input
              value={pathInput}
              onChange={e => setPathInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') addByPath() }}
              placeholder="s3://버킷/키 또는 키 입력 후 Enter"
              spellCheck={false}
              className="flex-1 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 font-mono placeholder-zinc-600 focus:outline-none focus:border-blue-500"
            />
            <button
              onClick={addByPath}
              disabled={!pathInput.trim()}
              className="px-2.5 py-1 bg-zinc-700 hover:bg-zinc-600 disabled:bg-zinc-800 disabled:text-zinc-600 text-zinc-200 text-xs rounded transition-colors"
            >
              추가
            </button>
          </div>
          {checkedKeys.size === 0 ? (
            <p className="text-xs text-zinc-600">왼쪽 트리에서 선택하거나 위에 경로를 입력하세요</p>
          ) : (
            <div className="space-y-0.5 max-h-40 overflow-y-auto">
              {[...checkedKeys].map(k => (
                <div key={k} className="flex items-center gap-2 text-xs group">
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
          {preview && (
            <div className="mt-2 pt-2 border-t border-zinc-700 flex gap-4 text-xs text-zinc-400">
              <span><span className="text-zinc-200">{preview.totalFiles}</span>개 파일</span>
              <span><span className="text-zinc-200">{formatBytes(preview.totalBytes)}</span></span>
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
          <div className="text-[11px] text-zinc-500 mt-1 flex items-center gap-3">
            <span>여유 공간: {freeSpace == null ? '—' : <span className="text-zinc-300">{formatBytes(freeSpace)}</span>}</span>
            {preview && freeSpace != null && preview.totalBytes > freeSpace && (
              <span className="text-amber-400">⚠ 공간 부족 가능 (전송 {formatBytes(preview.totalBytes)})</span>
            )}
          </div>
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

        {/* 다운로드 버튼 */}
        <button
          onClick={() => run(handleDownload)}
          disabled={!!isRunning || submitting || !state.selectedBucket || checkedKeys.size === 0}
          className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium py-2.5 rounded-lg transition-[background-color,scale] duration-150 active:scale-[0.96]"
        >
          <Download size={15} />
          {submitting ? '시작 중...' : '다운로드 시작'}
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
