import { Wifi, WifiOff, User, Globe } from 'lucide-react'
import { useAppStore } from '../store/appStore'

export function ConnectBar() {
  const { state } = useAppStore()
  const { connection } = state

  return (
    <header className="h-10 flex items-center gap-3 px-4 bg-zinc-950 border-b border-zinc-800 shrink-0 select-none">
      {/* 로고 */}
      <div className="flex items-center gap-2 font-semibold text-sm text-zinc-200 mr-2">
        <img src="./favicon.svg" alt="S3" className="w-5 h-5" />
        S3 Manager
      </div>

      <div className="w-px h-4 bg-zinc-700" />

      {/* 연결 상태 */}
      {connection.connected ? (
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
      )}
    </header>
  )
}
