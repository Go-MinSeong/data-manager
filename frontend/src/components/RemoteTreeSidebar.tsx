import { useState, useCallback, useEffect } from 'react'
import {
  ChevronRight,
  ChevronDown,
  Folder,
  FolderOpen,
  FileIcon,
  Server,
  RefreshCw,
  AlertCircle,
  Search,
  X,
  ArrowUp,
  CornerDownLeft,
  Star,
  ChevronRight as Chevron,
  Copy,
  FolderInput,
} from 'lucide-react'
import * as api from '../lib/api'
import { useAppStore } from '../store/appStore'
import { copyText } from '../lib/clipboard'
import { ContextMenu, type MenuItem } from './ContextMenu'
import type { TreeNode } from '../types'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

interface RemoteTreeSidebarProps {
  checkedKeys: Set<string>
  onCheckedChange: (keys: Set<string>) => void
  onSelectDir?: (dir: string) => void
  selectedDir?: string
  /** 우클릭 "업로드 위치로 설정" — 해당 경로를 업로드 대상으로 지정 */
  onSetUploadDest?: (dir: string) => void
}

export function RemoteTreeSidebar({
  checkedKeys,
  onCheckedChange,
  onSelectDir,
  selectedDir,
  onSetUploadDest,
}: RemoteTreeSidebarProps) {
  const { state, dispatch } = useAppStore()
  const connected = state.remoteConnection.connected
  const [menu, setMenu] = useState<{ x: number; y: number; items: MenuItem[] } | null>(null)

  const openMenu = (e: React.MouseEvent, items: MenuItem[]) => {
    e.preventDefault()
    e.stopPropagation()
    setMenu({ x: e.clientX, y: e.clientY, items })
  }

  const doCopy = async (text: string) => {
    const ok = await copyText(text)
    toast(ok ? '경로를 복사했습니다.' : '복사 실패', ok ? 'success' : 'error')
  }
  const [rootPath, setRootPath] = useState<string>('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [children, setChildren] = useState<Map<string, TreeNode[]>>(new Map())
  const [loading, setLoading] = useState<Set<string>>(new Set())
  const [rootLoading, setRootLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [pathInput, setPathInput] = useState('')  // 편집 가능한 루트 경로

  const toast = (message: string, variant: 'error' | 'success' | 'info' = 'error') => {
    dispatch({ type: 'ADD_TOAST', payload: { id: Date.now().toString(), message, variant } })
  }

  // path 디렉터리 한 레벨을 로드하여 children 맵에 저장한다.
  const loadDir = useCallback(async (path: string) => {
    if (loading.has(path)) return
    setLoading(prev => new Set(prev).add(path))
    try {
      const res = await api.getRemoteObjects(path || undefined)
      const nodes: TreeNode[] = [
        ...res.folders.map(f => ({
          key: f.key, // 트레일링 슬래시 포함 절대 경로
          name: f.name,
          isFolder: true as const,
        })),
        ...res.objects.map(o => ({
          key: o.key,
          name: o.key.split('/').pop() || o.key,
          isFolder: false as const,
          size: o.size,
          lastModified: o.lastModified,
        })),
      ]
      setChildren(prev => new Map(prev).set(path || res.prefix, nodes))
      return res.prefix
    } catch (e) {
      if (api.isDisconnectError(e)) {
        dispatch({ type: 'SET_REMOTE_CONNECTION', payload: { connected: false } })
        toast('원격 연결이 끊겼습니다. 다시 연결하세요.')
        return
      }
      toast(e instanceof Error ? e.message : '원격 목록 로드 실패')
    } finally {
      setLoading(prev => {
        const s = new Set(prev)
        s.delete(path)
        return s
      })
    }
  }, [loading])

  // path 미지정 시 홈 디렉터리(기본), 지정 시 해당 절대 경로를 트리 루트로 로드한다.
  const loadRoot = useCallback(async (path?: string) => {
    setRootLoading(true)
    setError(null)
    try {
      const res = await api.getRemoteObjects(path || undefined)
      const nodes: TreeNode[] = [
        ...res.folders.map(f => ({ key: f.key, name: f.name, isFolder: true as const })),
        ...res.objects.map(o => ({
          key: o.key,
          name: o.key.split('/').pop() || o.key,
          isFolder: false as const,
          size: o.size,
          lastModified: o.lastModified,
        })),
      ]
      setRootPath(res.prefix)
      setPathInput(res.prefix)
      setExpanded(new Set())
      setChildren(new Map([[res.prefix, nodes]]))
      onSelectDir?.(res.prefix)
    } catch (e) {
      if (api.isDisconnectError(e)) {
        dispatch({ type: 'SET_REMOTE_CONNECTION', payload: { connected: false } })
        toast('원격 연결이 끊겼습니다. 다시 연결하세요.')
        return
      }
      // 경로 문제(400 등)는 연결을 유지하고 토스트만 — 직전 경로 유지
      toast(e instanceof Error ? e.message : '경로를 열 수 없습니다')
    } finally {
      setRootLoading(false)
    }
  }, [])

  useEffect(() => {
    if (connected) {
      // 프로파일에 저장된 기본 폴더가 있으면 거기서, 없으면 홈에서 시작
      void loadRoot(state.remoteConnection.defaultPath || undefined)
    } else {
      setRootPath('')
      setChildren(new Map())
      setExpanded(new Set())
    }
  }, [connected]) // eslint-disable-line react-hooks/exhaustive-deps

  const saveDefaultFolder = async () => {
    const name = state.remoteConnection.profileName
    if (!name) {
      toast('프로파일로 연결한 경우에만 기본 폴더를 저장할 수 있습니다.', 'info')
      return
    }
    try {
      await api.setRemoteDefaultPath(name, rootPath)
      dispatch({
        type: 'SET_REMOTE_CONNECTION',
        payload: { ...state.remoteConnection, defaultPath: rootPath },
      })
      toast(`기본 폴더로 저장했습니다: ${rootPath}`, 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : '기본 폴더 저장 실패')
    }
  }

  const toggleFolder = async (folderKey: string) => {
    const dirPath = folderKey.replace(/\/$/, '') // 트레일링 슬래시 제거 = 디렉터리 경로
    if (expanded.has(folderKey)) {
      setExpanded(prev => {
        const s = new Set(prev)
        s.delete(folderKey)
        return s
      })
    } else {
      setExpanded(prev => new Set(prev).add(folderKey))
      if (!children.has(dirPath)) await loadDir(dirPath)
      onSelectDir?.(dirPath)
    }
  }

  const toggleCheck = (nodeKey: string) => {
    const next = new Set(checkedKeys)
    if (next.has(nodeKey)) next.delete(nodeKey)
    else next.add(nodeKey)
    onCheckedChange(next)
  }

  const renderNodes = (nodes: TreeNode[], depth: number) => {
    return nodes.map(node => {
      const isExpanded = expanded.has(node.key)
      const dirPath = node.key.replace(/\/$/, '')
      const childNodes = children.get(dirPath) ?? []
      const isLoading = loading.has(dirPath)
      const isChecked = checkedKeys.has(node.key)
      const isSelectedDir = node.isFolder && selectedDir === dirPath

      return (
        <div key={node.key}>
          <div
            className={`flex items-center gap-1.5 py-0.5 px-2 rounded cursor-pointer text-xs group transition-colors hover:bg-zinc-800 ${
              isChecked || isSelectedDir ? 'bg-zinc-800/50' : ''
            }`}
            style={{ paddingLeft: `${depth * 14 + 8}px` }}
            onContextMenu={e =>
              openMenu(
                e,
                node.isFolder
                  ? [
                      { label: '업로드 위치로 설정', icon: <FolderInput size={13} />, onClick: () => onSetUploadDest?.(dirPath) },
                      { label: '경로 복사', icon: <Copy size={13} />, onClick: () => doCopy(dirPath) },
                    ]
                  : [{ label: '경로 복사', icon: <Copy size={13} />, onClick: () => doCopy(node.key) }],
              )
            }
          >
            <span
              onClick={() => node.isFolder && toggleFolder(node.key)}
              className="w-4 h-4 flex items-center justify-center shrink-0 text-zinc-500"
            >
              {node.isFolder ? (
                isLoading ? (
                  <div className="w-3 h-3 border border-zinc-600 border-t-zinc-400 rounded-full animate-spin" />
                ) : isExpanded ? (
                  <ChevronDown size={12} />
                ) : (
                  <ChevronRight size={12} />
                )
              ) : null}
            </span>

            <input
              type="checkbox"
              checked={isChecked}
              onChange={() => toggleCheck(node.key)}
              className="w-3.5 h-3.5 accent-blue-500 shrink-0"
              onClick={e => e.stopPropagation()}
            />

            <span
              className="flex items-center gap-1.5 flex-1 min-w-0 text-zinc-300"
              onClick={() => node.isFolder && toggleFolder(node.key)}
            >
              {node.isFolder ? (
                isExpanded ? (
                  <FolderOpen size={13} className="text-yellow-400 shrink-0" />
                ) : (
                  <Folder size={13} className="text-yellow-400 shrink-0" />
                )
              ) : (
                <FileIcon size={13} className="text-zinc-500 shrink-0" />
              )}
              <span className="truncate">{node.name}</span>
            </span>

            {!node.isFolder && node.size !== undefined && (
              <span className="text-zinc-600 text-[10px] shrink-0 pl-1">{formatSize(node.size)}</span>
            )}
          </div>

          {node.isFolder && isExpanded && childNodes.length > 0 && (
            <div>{renderNodes(childNodes, depth + 1)}</div>
          )}
          {node.isFolder && isExpanded && childNodes.length === 0 && !isLoading && (
            <div className="text-[11px] text-zinc-600 py-0.5" style={{ paddingLeft: `${(depth + 1) * 14 + 24}px` }}>
              비어 있음
            </div>
          )}
        </div>
      )
    })
  }

  const rootNodes = children.get(rootPath) ?? []
  const q = filter.trim().toLowerCase()
  const visibleRootNodes = q
    ? rootNodes.filter(n => n.name.toLowerCase().includes(q))
    : rootNodes

  return (
    <aside className="w-full h-full flex flex-col bg-zinc-950 border-r border-zinc-800">
      {/* 헤더: 루트 경로 설정 */}
      <div className="px-2 py-2 border-b border-zinc-800 space-y-1.5">
        <div className="flex items-center justify-between px-1">
          <span className="text-xs font-medium text-zinc-400">원격 경로</span>
          {connected && (
            <div className="flex items-center gap-0.5">
              {state.remoteConnection.profileName && (
                <button
                  onClick={saveDefaultFolder}
                  disabled={rootLoading}
                  title="이 폴더를 프로파일 기본 폴더로 저장"
                  className={`p-1 rounded hover:bg-zinc-800 transition-colors ${
                    state.remoteConnection.defaultPath === rootPath
                      ? 'text-yellow-400'
                      : 'text-zinc-500 hover:text-zinc-300'
                  }`}
                >
                  <Star size={12} />
                </button>
              )}
              <button
                onClick={() => {
                  const parent =
                    rootPath === '/' || !rootPath
                      ? '/'
                      : rootPath.replace(/\/[^/]+\/?$/, '') || '/'
                  void loadRoot(parent)
                }}
                disabled={rootLoading || rootPath === '/'}
                title="상위 폴더로"
                className="p-1 rounded text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 disabled:opacity-40 transition-colors"
              >
                <ArrowUp size={12} />
              </button>
              <button
                onClick={() => void loadRoot(rootPath)}
                disabled={rootLoading}
                title="새로고침"
                className="p-1 rounded text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 transition-colors"
              >
                <RefreshCw size={12} className={rootLoading ? 'animate-spin' : ''} />
              </button>
            </div>
          )}
        </div>
        {/* breadcrumb */}
        {connected && rootPath && (
          <div className="flex items-center gap-0.5 px-1 overflow-x-auto whitespace-nowrap text-[11px]">
            <button onClick={() => void loadRoot('/')} className="px-1 rounded hover:bg-zinc-800 text-zinc-500 hover:text-zinc-200">/</button>
            {rootPath.split('/').filter(Boolean).map((seg, i, arr) => {
              const path = '/' + arr.slice(0, i + 1).join('/')
              return (
                <span key={path} className="flex items-center gap-0.5">
                  <Chevron size={9} className="text-zinc-600" />
                  <button
                    onClick={() => void loadRoot(path)}
                    className={`px-1 rounded hover:bg-zinc-800 ${i === arr.length - 1 ? 'text-zinc-200' : 'text-zinc-400'}`}
                  >
                    {seg}
                  </button>
                </span>
              )
            })}
          </div>
        )}
        {connected && (
          <div className="relative">
            <input
              value={pathInput}
              onChange={e => setPathInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') void loadRoot(pathInput.trim())
              }}
              placeholder="/path/to/dir (Enter로 이동)"
              spellCheck={false}
              className="w-full bg-zinc-900 border border-zinc-800 rounded pl-2 pr-7 py-1 text-xs text-zinc-200 font-mono placeholder-zinc-600 focus:outline-none focus:border-zinc-600"
            />
            <button
              onClick={() => void loadRoot(pathInput.trim())}
              disabled={rootLoading}
              title="이동"
              className="absolute right-1 top-1/2 -translate-y-1/2 p-0.5 rounded text-zinc-500 hover:text-zinc-200"
            >
              <CornerDownLeft size={12} />
            </button>
          </div>
        )}
      </div>

      {/* 검색 */}
      {connected && rootNodes.length > 0 && (
        <div className="px-2 py-1.5 border-b border-zinc-800/60">
          <div className="relative">
            <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-zinc-600" />
            <input
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="이름 검색..."
              className="w-full bg-zinc-900 border border-zinc-800 rounded pl-7 pr-6 py-1 text-xs text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-zinc-600"
            />
            {filter && (
              <button
                onClick={() => setFilter('')}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-zinc-600 hover:text-zinc-300"
              >
                <X size={12} />
              </button>
            )}
          </div>
        </div>
      )}

      {/* 트리 내용 */}
      <div className="flex-1 overflow-y-auto py-1">
        {!connected ? (
          <div className="flex flex-col items-center justify-center h-32 text-zinc-600 text-xs gap-2">
            <Server size={20} />
            <span>연결 후 디렉터리가 표시됩니다</span>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center h-32 text-red-500 text-xs gap-2 px-3">
            <AlertCircle size={16} />
            <span className="text-center">{error}</span>
            <button onClick={() => void loadRoot(rootPath || undefined)} className="text-blue-400 hover:text-blue-300 underline">
              다시 시도
            </button>
          </div>
        ) : rootLoading ? (
          <div className="flex flex-col items-center justify-center h-32 text-zinc-600 text-xs gap-2">
            <div className="w-5 h-5 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
            <span>로드 중...</span>
          </div>
        ) : rootNodes.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-zinc-600 text-xs gap-2">
            <Server size={20} />
            <span>비어 있습니다</span>
          </div>
        ) : visibleRootNodes.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-zinc-600 text-xs gap-2">
            <Search size={18} />
            <span>검색 결과가 없습니다</span>
          </div>
        ) : (
          <div>{renderNodes(visibleRootNodes, 0)}</div>
        )}
      </div>

      {menu && (
        <ContextMenu x={menu.x} y={menu.y} items={menu.items} onClose={() => setMenu(null)} />
      )}
    </aside>
  )
}
