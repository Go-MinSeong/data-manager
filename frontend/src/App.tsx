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
import * as api from './lib/api'

const SIDEBAR_MIN = 180
const SIDEBAR_MAX = 700

function AppInner() {
  const [state, dispatch] = useReducer(appReducer, initialAppState)
  const [checkedKeys, setCheckedKeys] = useState<Set<string>>(new Set())
  const [selectedRemoteDir, setSelectedRemoteDir] = useState<string>('')

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
                  />
                ) : (
                  <RemoteTreeSidebar
                    checkedKeys={checkedKeys}
                    onCheckedChange={setCheckedKeys}
                    onSelectDir={setSelectedRemoteDir}
                    selectedDir={selectedRemoteDir}
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
                />
              ) : (
                <RemoteMainPanel
                  checkedKeys={checkedKeys}
                  selectedDir={selectedRemoteDir}
                />
              )}
            </>
          )}
        </div>

        {/* 토스트 알림 */}
        <ToastContainer />
      </div>
    </AppContext.Provider>
  )
}

export default AppInner
