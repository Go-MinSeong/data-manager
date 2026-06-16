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
} from 'lucide-react'
import * as api from '../lib/api'
import { useAppStore } from '../store/appStore'
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
}

export function RemoteTreeSidebar({
  checkedKeys,
  onCheckedChange,
  onSelectDir,
  selectedDir,
}: RemoteTreeSidebarProps) {
  const { state, dispatch } = useAppStore()
  const connected = state.remoteConnection.connected
  const [rootPath, setRootPath] = useState<string>('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [children, setChildren] = useState<Map<string, TreeNode[]>>(new Map())
  const [loading, setLoading] = useState<Set<string>>(new Set())
  const [rootLoading, setRootLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
      toast(e instanceof Error ? e.message : '원격 목록 로드 실패')
    } finally {
      setLoading(prev => {
        const s = new Set(prev)
        s.delete(path)
        return s
      })
    }
  }, [loading])

  const loadRoot = useCallback(async () => {
    setRootLoading(true)
    setError(null)
    try {
      const res = await api.getRemoteObjects()
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
      setChildren(prev => new Map(prev).set(res.prefix, nodes))
      onSelectDir?.(res.prefix)
    } catch (e) {
      const msg = e instanceof Error ? e.message : '원격 목록 로드 실패'
      setError(msg)
    } finally {
      setRootLoading(false)
    }
  }, [])

  useEffect(() => {
    if (connected) {
      void loadRoot()
    } else {
      setRootPath('')
      setChildren(new Map())
      setExpanded(new Set())
    }
  }, [connected])

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

  return (
    <aside className="w-full h-full flex flex-col bg-zinc-950 border-r border-zinc-800">
      {/* 헤더 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
        <span className="text-xs font-medium text-zinc-400 truncate" title={rootPath}>
          {rootPath || '원격 탐색기'}
        </span>
        {connected && (
          <button
            onClick={() => {
              setChildren(new Map())
              setExpanded(new Set())
              void loadRoot()
            }}
            disabled={rootLoading}
            className="p-1 rounded text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 transition-colors shrink-0"
          >
            <RefreshCw size={12} className={rootLoading ? 'animate-spin' : ''} />
          </button>
        )}
      </div>

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
            <button onClick={loadRoot} className="text-blue-400 hover:text-blue-300 underline">
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
        ) : (
          <div>{renderNodes(rootNodes, 0)}</div>
        )}
      </div>
    </aside>
  )
}
