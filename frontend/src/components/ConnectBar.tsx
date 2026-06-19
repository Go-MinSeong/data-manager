import { useState } from 'react'
import { Wifi, WifiOff, User, Globe, Server, Cloud, LogOut, ArrowLeftRight, Settings } from 'lucide-react'
import { useAppStore } from '../store/appStore'
import * as api from '../lib/api'
import { SettingsPanel } from './SettingsPanel'
import type { SourceMode } from '../types'

export function ConnectBar() {
  const { state, dispatch } = useAppStore()
  const { mode, connection, remoteConnection } = state
  const [settingsOpen, setSettingsOpen] = useState(false)

  const modes: { id: SourceMode; label: string; icon: React.ReactNode }[] = [
    { id: 's3', label: 'S3', icon: <Cloud size={12} /> },
    { id: 'remote', label: '원격', icon: <Server size={12} /> },
    { id: 'transfer', label: '전송', icon: <ArrowLeftRight size={12} /> },
  ]

  // 연결 해제 버튼은 단일 엔드포인트 모드(s3/remote)에서만 표시
  const isConnected =
    mode === 's3'
      ? connection.connected
      : mode === 'remote'
        ? remoteConnection.connected
        : false

  const handleDisconnect = async () => {
    try {
      if (mode === 's3') {
        await api.disconnect()
        dispatch({ type: 'SET_CONNECTION', payload: { connected: false } })
      } else {
        await api.remoteDisconnect()
        dispatch({ type: 'SET_REMOTE_CONNECTION', payload: { connected: false } })
      }
    } catch {
      // 실패해도 화면 상태는 해제로 — 재연결 화면에서 다시 시도
      if (mode === 's3') dispatch({ type: 'SET_CONNECTION', payload: { connected: false } })
      else dispatch({ type: 'SET_REMOTE_CONNECTION', payload: { connected: false } })
    }
  }

  return (
    <>
    <header className="pywebview-drag-region h-11 flex items-center gap-3 pl-20 pr-4 bg-zinc-950 border-b border-zinc-800 shrink-0 select-none">
      {/* 로고 — 구름은 테마 액센트(currentColor), 글자는 흰색 */}
      <div className="flex items-center gap-2 font-semibold text-sm text-zinc-200 mr-1">
        <svg viewBox="0 0 64 64" className="w-5 h-5 text-blue-500 shrink-0" fill="currentColor" aria-label="Data">
          <g>
            <circle cx="17.9" cy="33.9" r="8.3" />
            <circle cx="28.2" cy="28.8" r="10.6" />
            <circle cx="38.4" cy="29.4" r="9.9" />
            <circle cx="47.4" cy="33.9" r="8.3" />
            <rect x="3.8" y="30.1" width="56.4" height="22.4" rx="10.9" />
          </g>
          <text x="32" y="41.5" textAnchor="middle" dominantBaseline="central"
            fontFamily="Helvetica, Arial, sans-serif" fontWeight="700" fontSize="16" fill="#ffffff">DATA</text>
        </svg>
        Data Manager
      </div>

      {/* 모드 토글 */}
      <div className="flex gap-0.5 bg-zinc-800 p-0.5 rounded-md">
        {modes.map(m => (
          <button
            key={m.id}
            onClick={() => dispatch({ type: 'SET_MODE', payload: m.id })}
            className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors ${
              mode === m.id
                ? 'bg-zinc-700 text-zinc-100'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            {m.icon}
            {m.label}
          </button>
        ))}
      </div>

      <div className="w-px h-4 bg-zinc-700" />

      {/* 연결 상태 */}
      {mode === 'transfer' ? (
        <div className="flex items-center gap-4 text-xs">
          <span className={`flex items-center gap-1.5 ${connection.connected ? 'text-emerald-400' : 'text-zinc-500'}`}>
            <Cloud size={12} />
            S3 {connection.connected ? '연결됨' : '미연결'}
          </span>
          <span className={`flex items-center gap-1.5 ${remoteConnection.connected ? 'text-emerald-400' : 'text-zinc-500'}`}>
            <Server size={12} />
            원격 {remoteConnection.connected ? `${remoteConnection.username}@${remoteConnection.host}` : '미연결'}
          </span>
        </div>
      ) : mode === 's3' ? (
        connection.connected ? (
          <div className="flex items-center gap-4 text-xs text-zinc-400">
            <span className="flex items-center gap-1.5 text-emerald-400">
              <Wifi size={13} />
              <span className="font-medium">연결됨</span>
            </span>
            {connection.identity && (
              <span className="flex items-center gap-1">
                <User size={12} className="text-zinc-500" />
                {connection.identity.account}
              </span>
            )}
            {connection.region && (
              <span className="flex items-center gap-1">
                <Globe size={12} className="text-zinc-500" />
                {connection.region}
              </span>
            )}
            {connection.identity && (
              <span className="text-zinc-600 hidden xl:block truncate max-w-xs">
                {connection.identity.arn}
              </span>
            )}
          </div>
        ) : (
          <span className="flex items-center gap-1.5 text-xs text-zinc-500">
            <WifiOff size={13} />
            연결 안 됨
          </span>
        )
      ) : remoteConnection.connected ? (
        <div className="flex items-center gap-4 text-xs text-zinc-400">
          <span className="flex items-center gap-1.5 text-emerald-400">
            <Wifi size={13} />
            <span className="font-medium">연결됨</span>
          </span>
          <span className="flex items-center gap-1">
            <User size={12} className="text-zinc-500" />
            {remoteConnection.username}@{remoteConnection.host}
          </span>
          {remoteConnection.homeDir && (
            <span className="text-zinc-600 hidden lg:block truncate max-w-xs font-mono">
              {remoteConnection.homeDir}
            </span>
          )}
        </div>
      ) : (
        <span className="flex items-center gap-1.5 text-xs text-zinc-500">
          <WifiOff size={13} />
          연결 안 됨
        </span>
      )}

      <div className="ml-auto flex items-center gap-1">
        {isConnected && (
          <button
            onClick={handleDisconnect}
            title={mode === 's3' ? '연결 해제' : '연결 해제 (다른 서버로 전환)'}
            className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-200 px-2 py-1 rounded hover:bg-zinc-800 transition-colors"
          >
            <LogOut size={12} />
            연결 해제
          </button>
        )}
        <button
          onClick={() => setSettingsOpen(true)}
          title="설정"
          className="p-1.5 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
        >
          <Settings size={14} />
        </button>
      </div>
    </header>
    {settingsOpen && <SettingsPanel onClose={() => setSettingsOpen(false)} />}
    </>
  )
}
