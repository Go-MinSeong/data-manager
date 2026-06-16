import { Download, Upload, History } from 'lucide-react'
import { useAppStore } from '../store/appStore'
import { RemoteDownloadPanel } from './RemoteDownloadPanel'
import { RemoteUploadPanel } from './RemoteUploadPanel'
import { JobsPanel } from './JobsPanel'
import type { PanelTab } from '../types'

const TABS: { id: PanelTab; label: string; icon: React.ReactNode }[] = [
  { id: 'download', label: '다운로드', icon: <Download size={14} /> },
  { id: 'upload', label: '업로드', icon: <Upload size={14} /> },
  { id: 'jobs', label: '작업 이력', icon: <History size={14} /> },
]

interface RemoteMainPanelProps {
  checkedKeys: Set<string>
  selectedDir?: string
}

export function RemoteMainPanel({ checkedKeys, selectedDir }: RemoteMainPanelProps) {
  const { state, dispatch } = useAppStore()

  return (
    <div className="flex flex-col flex-1 min-w-0 bg-zinc-900">
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

      <div className="flex-1 overflow-y-auto">
        <div className={state.activeTab === 'download' ? '' : 'hidden'}>
          <RemoteDownloadPanel checkedKeys={checkedKeys} />
        </div>
        <div className={state.activeTab === 'upload' ? '' : 'hidden'}>
          <RemoteUploadPanel selectedDir={selectedDir} />
        </div>
        {state.activeTab === 'jobs' && <JobsPanel />}
      </div>
    </div>
  )
}
