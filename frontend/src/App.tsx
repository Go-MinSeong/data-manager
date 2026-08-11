import { useReducer, useEffect, useState, useRef, useCallback } from 'react'
import { AppContext, appReducer, initialAppState } from './store/appStore'
import { ConnectBar } from './components/ConnectBar'
import { ConnectPanel } from './components/ConnectPanel'
import { TreeSidebar } from './components/TreeSidebar'
import { MainPanel } from './components/MainPanel'
import { RemoteConnectPanel } from './components/RemoteConnectPanel'
import { RemoteTreeSidebar } from './components/RemoteTreeSidebar'
import { RemoteMainPanel } from './components/RemoteMainPanel'
import { TransferView } from './components/TransferView'
import { ToastContainer } from './components/Toast'
import { applyTheme, loadTheme } from './lib/themes'
import * as api from './lib/api'

const SIDEBAR_MIN = 180
const SIDEBAR_MAX = 700

function AppInner() {
  const [state, dispatch] = useReducer(appReducer, initialAppState)
  const [checkedKeys, setCheckedKeys] = useState<Set<string>>(new Set())
  const [selectedRemoteDir, setSelectedRemoteDir] = useState<string>('')

  // 트리 우클릭 "업로드 위치로 설정" → 업로드 패널에 대상 경로 주입(nonce로 트리거)
  const [s3UploadPreset, setS3UploadPreset] = useState({ prefix: '', nonce: 0 })
  const [remoteUploadPreset, setRemoteUploadPreset] = useState({ dir: '', nonce: 0 })

  // 업로드 패널에서 새 폴더 생성 → 트리의 해당 prefix 캐시 무효화 후 새로고침(nonce로 트리거)
  const [s3FolderCreated, setS3FolderCreated] = useState({ bucket: '', prefix: '', nonce: 0 })
  const handleS3FolderCreated = useCallback((bucket: string, prefix: string) => {
    setS3FolderCreated(p => ({ bucket, prefix, nonce: p.nonce + 1 }))
  }, [])

  const handleSetS3Upload = useCallback((bucket: string, prefix: string) => {
    dispatch({ type: 'SET_BUCKET', payload: bucket })
    setS3UploadPreset(p => ({ prefix, nonce: p.nonce + 1 }))
    dispatch({ type: 'SET_TAB', payload: 'upload' })
  }, [])

  const handleSetRemoteUpload = useCallback((dir: string) => {
    setRemoteUploadPreset(p => ({ dir, nonce: p.nonce + 1 }))
    dispatch({ type: 'SET_TAB', payload: 'upload' })
  }, [])

  // 드래그-드롭 파일 — 셸(pywebview)이 window.__onFilesDropped(paths)로 절대경로 전달
  const [s3UploadFiles, setS3UploadFiles] = useState({ paths: [] as string[], nonce: 0 })
  const [remoteUploadFiles, setRemoteUploadFiles] = useState({ paths: [] as string[], nonce: 0 })
  const [dropBusy, setDropBusy] = useState(false)

  useEffect(() => {
    const w = window as unknown as {
      __onFilesDropStart?: () => void
      __onFilesDropped?: (p: string[]) => void
    }
    // 드롭이 웹뷰에 전달되는 즉시 호출 — 경로 처리/렌더 동안 로딩을 보여준다.
    w.__onFilesDropStart = () => setDropBusy(true)
    w.__onFilesDropped = (paths) => {
      setDropBusy(false)
      if (!Array.isArray(paths) || paths.length === 0) return
      if (state.mode === 's3' && state.activeTab === 'upload') {
        setS3UploadFiles(p => ({ paths, nonce: p.nonce + 1 }))
      } else if (state.mode === 'remote' && state.activeTab === 'upload') {
        setRemoteUploadFiles(p => ({ paths, nonce: p.nonce + 1 }))
      } else {
        dispatch({ type: 'ADD_TOAST', payload: { id: '', message: '업로드 탭에서 파일을 놓아주세요.', variant: 'info' } })
        return
      }
      dispatch({ type: 'ADD_TOAST', payload: { id: '', message: `${paths.length}개 항목을 추가했습니다.`, variant: 'success' } })
    }
  }, [state.mode, state.activeTab])

  // 저장된 테마 적용 (최초 1회)
  useEffect(() => { applyTheme(loadTheme()) }, [])

  // 모드 전환 시 선택 항목 초기화 (S3 키와 원격 경로는 의미가 다르다)
  useEffect(() => {
    setCheckedKeys(new Set())
  }, [state.mode])

  // 사이드바 폭 (드래그로 조절, localStorage에 유지)
  const [sidebarWidth, setSidebarWidth] = useState<number>(() => {
    const saved = Number(localStorage.getItem('s3m.sidebarWidth'))
    return saved >= SIDEBAR_MIN && saved <= SIDEBAR_MAX ? saved : 256
  })
  const draggingRef = useRef(false)
  const widthRef = useRef(sidebarWidth)

  const startDrag = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    draggingRef.current = true
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [])

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return
      const w = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, e.clientX))
      widthRef.current = w
      setSidebarWidth(w)
    }
    const onUp = () => {
      if (!draggingRef.current) return
      draggingRef.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      localStorage.setItem('s3m.sidebarWidth', String(widthRef.current))
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  // 초기화 시 S3·원격 연결 상태를 모두 조회
  useEffect(() => {
    api.getConnection()
      .then(res => dispatch({ type: 'SET_CONNECTION', payload: res }))
      .catch(() => { /* 백엔드 미연결이면 무시 */ })
    api.getRemoteConnection()
      .then(res => dispatch({ type: 'SET_REMOTE_CONNECTION', payload: res }))
      .catch(() => { /* 무시 */ })
  }, [])

  const isConnected =
    state.mode === 's3'
      ? state.connection.connected
      : state.remoteConnection.connected

  return (
    <AppContext.Provider value={{ state, dispatch }}>
      <div className="flex flex-col h-screen bg-zinc-950 text-zinc-200 overflow-hidden">
        {/* 상단 연결 상태 바 */}
        <ConnectBar />

        {/* 메인 영역 */}
        <div className="flex flex-1 min-h-0">
          {state.mode === 'transfer' ? (
            <TransferView />
          ) : !isConnected ? (
            // 미연결: 연결 화면 (모드별)
            state.mode === 's3' ? <ConnectPanel /> : <RemoteConnectPanel />
          ) : (
            // 연결됨: 사이드바 + 드래그 핸들 + 패널
            <>
              <div style={{ width: sidebarWidth }} className="shrink-0 h-full min-h-0">
                {state.mode === 's3' ? (
                  <TreeSidebar
                    checkedKeys={checkedKeys}
                    onCheckedChange={setCheckedKeys}
                    onSetUploadDest={handleSetS3Upload}
                    refreshSignal={s3FolderCreated}
                  />
                ) : (
                  <RemoteTreeSidebar
                    checkedKeys={checkedKeys}
                    onCheckedChange={setCheckedKeys}
                    onSelectDir={setSelectedRemoteDir}
                    selectedDir={selectedRemoteDir}
                    onSetUploadDest={handleSetRemoteUpload}
                  />
                )}
              </div>
              {/* 좌우 크기 조절 드래그 바 */}
              <div
                onMouseDown={startDrag}
                title="드래그하여 너비 조절"
                className="w-1 shrink-0 cursor-col-resize bg-zinc-800 hover:bg-blue-500 active:bg-blue-500 transition-colors"
              />
              {state.mode === 's3' ? (
                <MainPanel
                  checkedKeys={checkedKeys}
                  onCheckedChange={setCheckedKeys}
                  uploadPreset={s3UploadPreset}
                  uploadFilesPreset={s3UploadFiles}
                  onFolderCreated={handleS3FolderCreated}
                />
              ) : (
                <RemoteMainPanel
                  checkedKeys={checkedKeys}
                  onCheckedChange={setCheckedKeys}
                  selectedDir={selectedRemoteDir}
                  uploadPreset={remoteUploadPreset}
                  uploadFilesPreset={remoteUploadFiles}
                />
              )}
            </>
          )}
        </div>

        {/* 드롭한 파일 처리 중 표시 */}
        {dropBusy && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 pointer-events-none">
            <div className="flex items-center gap-2 bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-3 shadow-2xl">
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span className="text-sm text-zinc-200">파일 추가 중…</span>
            </div>
          </div>
        )}

        {/* 토스트 알림 */}
        <ToastContainer />
      </div>
    </AppContext.Provider>
  )
}

export default AppInner
