import { Download, Upload, RefreshCw, History } from 'lucide-react'
import { useAppStore } from '../store/appStore'
import { DownloadPanel } from './DownloadPanel'
import { UploadPanel } from './UploadPanel'
import { SyncPanel } from './SyncPanel'
import { JobsPanel } from './JobsPanel'
import type { PanelTab } from '../types'

const TABS: { id: PanelTab; label: string; icon: React.ReactNode }[] = [
  { id: 'download', label: '다운로드', icon: <Download size={14} /> },
  { id: 'upload', label: '업로드', icon: <Upload size={14} /> },
  { id: 'sync', label: '동기화', icon: <RefreshCw size={14} /> },
  { id: 'jobs', label: '작업 이력', icon: <History size={14} /> },
]

interface MainPanelProps {
  checkedKeys: Set<string>
  onCheckedChange?: (keys: Set<string>) => void
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function MainPanel({ checkedKeys, onCheckedChange: _onCheckedChange }: MainPanelProps) {
  const { state, dispatch } = useAppStore()

  return (
    <div className="flex flex-col flex-1 min-w-0 bg-zinc-900">
      {/* 탭 바 */}
      <div className="flex gap-0.5 px-3 pt-3 border-b border-zinc-800 shrink-0">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => dispatch({ type: 'SET_TAB', payload: tab.id })}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-t-lg transition-colors -mb-px ${
              state.activeTab === tab.id
                ? 'bg-zinc-800 text-zinc-100 border border-b-zinc-800 border-zinc-700'
                : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50 border border-transparent'
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* 패널 콘텐츠 */}
      <div className="flex-1 overflow-y-auto">
        {state.activeTab === 'download' && (
          <DownloadPanel checkedKeys={checkedKeys} />
        )}
        {state.activeTab === 'upload' && <UploadPanel />}
        {state.activeTab === 'sync' && <SyncPanel />}
        {state.activeTab === 'jobs' && <JobsPanel />}
      </div>
    </div>
  )
}
