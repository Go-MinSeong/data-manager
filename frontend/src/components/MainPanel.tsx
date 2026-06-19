import { Download, Upload, History } from 'lucide-react'
import { useAppStore } from '../store/appStore'
import { DownloadPanel } from './DownloadPanel'
import { UploadPanel } from './UploadPanel'
import { JobsPanel } from './JobsPanel'
import type { PanelTab } from '../types'

const TABS: { id: PanelTab; label: string; icon: React.ReactNode }[] = [
  { id: 'download', label: '다운로드', icon: <Download size={14} /> },
  { id: 'upload', label: '업로드', icon: <Upload size={14} /> },
  { id: 'jobs', label: '작업 이력', icon: <History size={14} /> },
]

interface MainPanelProps {
  checkedKeys: Set<string>
  onCheckedChange?: (keys: Set<string>) => void
  uploadPreset?: { prefix: string; nonce: number }
  uploadFilesPreset?: { paths: string[]; nonce: number }
}

export function MainPanel({ checkedKeys, onCheckedChange, uploadPreset, uploadFilesPreset }: MainPanelProps) {
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

      {/* 패널 콘텐츠
          다운로드·업로드는 항상 마운트하고 숨김(display:none)으로 토글한다.
          탭을 이동해도 진행 중인 전송 job 상태(버튼 비활성 등)가 유지된다.
          작업 이력은 볼 때마다 새로 로드되도록 조건부 렌더 유지. */}
      <div className="flex-1 overflow-y-auto">
        <div className={state.activeTab === 'download' ? '' : 'hidden'}>
          <DownloadPanel checkedKeys={checkedKeys} onCheckedChange={onCheckedChange} />
        </div>
        <div className={state.activeTab === 'upload' ? '' : 'hidden'}>
          <UploadPanel preset={uploadPreset} filesPreset={uploadFilesPreset} />
        </div>
        {state.activeTab === 'jobs' && <JobsPanel />}
      </div>
    </div>
  )
}
