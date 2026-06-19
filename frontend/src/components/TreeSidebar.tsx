import { useState, useCallback, useEffect } from 'react'
import {
  ChevronRight,
  ChevronDown,
  Folder,
  FolderOpen,
  FileIcon,
  HardDrive,
  RefreshCw,
  AlertCircle,
  Eye,
  EyeOff,
  Search,
  X,
  Copy,
  FolderInput,
  Image as ImageIcon,
} from 'lucide-react'
import * as api from '../lib/api'
import { useAppStore } from '../store/appStore'
import { copyText } from '../lib/clipboard'
import { ContextMenu, type MenuItem } from './ContextMenu'
import { ImagePreview, isImagePath } from './ImagePreview'
import type { TreeNode } from '../types'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

interface TreeSidebarProps {
  checkedKeys: Set<string>
  onCheckedChange: (keys: Set<string>) => void
  onNodeSelect?: (bucket: string, prefix: string, isFolder: boolean) => void
  /** 우클릭 "업로드 위치로 설정" — 버킷+prefix를 업로드 대상으로 지정 */
  onSetUploadDest?: (bucket: string, prefix: string) => void
}

export function TreeSidebar({ checkedKeys, onCheckedChange, onNodeSelect, onSetUploadDest }: TreeSidebarProps) {
  const { state, dispatch } = useAppStore()
  const [menu, setMenu] = useState<{ x: number; y: number; items: MenuItem[] } | null>(null)
  const [preview, setPreview] = useState<{ src: string; title: string } | null>(null)

  const openImagePreview = async (bucket: string, key: string, name: string) => {
    try {
      const r = await api.getS3PreviewUrl(bucket, key)
      setPreview({ src: r.url, title: name })
    } catch (e) {
      toast(e instanceof Error ? e.message : '미리보기 실패')
    }
  }

  const openMenu = (e: React.MouseEvent, items: MenuItem[]) => {
    e.preventDefault()
    e.stopPropagation()
    setMenu({ x: e.clientX, y: e.clientY, items })
  }

  const doCopy = async (text: string) => {
    const ok = await copyText(text)
    toast(ok ? '경로를 복사했습니다.' : '복사 실패', ok ? 'success' : 'error')
  }
  const [buckets, setBuckets] = useState<{ name: string; region: string | null }[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [children, setChildren] = useState<Map<string, TreeNode[]>>(new Map())
  const [loading, setLoading] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [bucketLoading, setBucketLoading] = useState(false)
  const [hiddenBuckets, setHiddenBuckets] = useState<Set<string>>(new Set())
  const [showHidden, setShowHidden] = useState(false)
  const [filter, setFilter] = useState('')

  const toast = (message: string, variant: 'error' | 'success' | 'info' = 'error') => {
    dispatch({
      type: 'ADD_TOAST',
      payload: { id: Date.now().toString(), message, variant },
    })
  }

  const loadBuckets = useCallback(async () => {
    setBucketLoading(true)
    setError(null)
    try {
      const res = await api.getBuckets()
      setBuckets(res.buckets)
    } catch (e) {
      const msg = e instanceof Error ? e.message : '버킷 로드 실패'
      setError(msg)
      toast(msg)
    } finally {
      setBucketLoading(false)
    }
  }, [])

  useEffect(() => {
    if (state.connection.connected) {
      void loadBuckets()
      api.getPreferences()
        .then(p => setHiddenBuckets(new Set(p.hiddenBuckets)))
        .catch(() => { /* 무시 */ })
    } else {
      setBuckets([])
      setChildren(new Map())
      setExpanded(new Set())
    }
  }, [state.connection.connected])

  const toggleHidden = useCallback(async (name: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const next = new Set(hiddenBuckets)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    setHiddenBuckets(next)
    try {
      await api.setHiddenBuckets([...next])
    } catch {
      toast('숨김 설정 저장 실패')
    }
  }, [hiddenBuckets])

  const loadObjects = useCallback(async (bucket: string, prefix: string) => {
    const key = `${bucket}::${prefix}`
    if (loading.has(key)) return
    setLoading(prev => new Set(prev).add(key))
    try {
      const res = await api.getObjects(bucket, prefix || undefined)
      const nodes: TreeNode[] = [
        ...res.folders.map(f => ({
          key: f.key,
          name: f.name,
          isFolder: true as const,
          loaded: false,
          expanded: false,
        })),
        ...res.objects.map(o => ({
          key: o.key,
          name: o.key.split('/').pop() || o.key,
          isFolder: false as const,
          size: o.size,
          lastModified: o.lastModified,
        })),
      ]
      setChildren(prev => new Map(prev).set(key, nodes))
    } catch (e) {
      toast(e instanceof Error ? e.message : '오브젝트 로드 실패')
    } finally {
      setLoading(prev => {
        const s = new Set(prev)
        s.delete(key)
        return s
      })
    }
  }, [loading])

  const toggleBucket = async (bucket: string) => {
    dispatch({ type: 'SET_BUCKET', payload: bucket })
    const key = `bucket::${bucket}`
    if (expanded.has(key)) {
      setExpanded(prev => {
        const s = new Set(prev)
        s.delete(key)
        return s
      })
    } else {
      setExpanded(prev => new Set(prev).add(key))
      const childKey = `${bucket}::`
      if (!children.has(childKey)) {
        await loadObjects(bucket, '')
      }
    }
  }

  const toggleFolder = async (bucket: string, folderKey: string) => {
    const key = `folder::${folderKey}`
    if (expanded.has(key)) {
      setExpanded(prev => {
        const s = new Set(prev)
        s.delete(key)
        return s
      })
    } else {
      setExpanded(prev => new Set(prev).add(key))
      const childKey = `${bucket}::${folderKey}`
      if (!children.has(childKey)) {
        await loadObjects(bucket, folderKey)
      }
    }
  }

  const toggleCheck = (nodeKey: string, isFolder: boolean) => {
    const next = new Set(checkedKeys)
    if (next.has(nodeKey)) {
      next.delete(nodeKey)
    } else {
      next.add(nodeKey)
    }
    onCheckedChange(next)
    // 노드 선택 콜백
    const bucket = state.selectedBucket
    if (bucket && onNodeSelect) {
      onNodeSelect(bucket, isFolder ? nodeKey : nodeKey, isFolder)
    }
  }

  const renderNodes = (nodes: TreeNode[], bucket: string, depth: number) => {
    return nodes.map(node => {
      const folderExpKey = `folder::${node.key}`
      const isExpanded = expanded.has(folderExpKey)
      const childKey = `${bucket}::${node.key}`
      const childNodes = children.get(childKey) ?? []
      const isLoading = loading.has(childKey)
      const isChecked = checkedKeys.has(node.key)

      return (
        <div key={node.key}>
          <div
            className={`flex items-center gap-1.5 py-0.5 px-2 rounded cursor-pointer text-xs group transition-colors hover:bg-zinc-800 ${
              isChecked ? 'bg-zinc-800/50' : ''
            }`}
            style={{ paddingLeft: `${depth * 14 + 8}px` }}
            onContextMenu={e =>
              openMenu(
                e,
                node.isFolder
                  ? [
                      { label: '업로드 위치로 설정', icon: <FolderInput size={13} />, onClick: () => onSetUploadDest?.(bucket, node.key) },
                      { label: '경로 복사', icon: <Copy size={13} />, onClick: () => doCopy(node.key) },
                    ]
                  : [
                      ...(isImagePath(node.name)
                        ? [{ label: '미리보기', icon: <ImageIcon size={13} />, onClick: () => void openImagePreview(bucket, node.key, node.name) }]
                        : []),
                      { label: '경로 복사', icon: <Copy size={13} />, onClick: () => doCopy(node.key) },
                    ],
              )
            }
          >
            {/* 펼치기 아이콘 */}
            <span
              onClick={() => node.isFolder && toggleFolder(bucket, node.key)}
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

            {/* 체크박스 */}
            <input
              type="checkbox"
              checked={isChecked}
              onChange={() => toggleCheck(node.key, node.isFolder)}
              className="w-3.5 h-3.5 accent-blue-500 shrink-0"
              onClick={e => e.stopPropagation()}
            />

            {/* 아이콘 */}
            <span
              className="flex items-center gap-1.5 flex-1 min-w-0 text-zinc-300"
              onClick={() => {
                if (node.isFolder) void toggleFolder(bucket, node.key)
              }}
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

            {/* 파일 크기 */}
            {!node.isFolder && node.size !== undefined && (
              <span className="text-zinc-600 text-[10px] shrink-0 pl-1">{formatSize(node.size)}</span>
            )}
          </div>

          {/* 자식 노드 */}
          {node.isFolder && isExpanded && childNodes.length > 0 && (
            <div>{renderNodes(childNodes, bucket, depth + 1)}</div>
          )}
        </div>
      )
    })
  }

  // 필터 + 숨김 적용된 표시 대상 계산
  const q = filter.trim().toLowerCase()
  const matchesFilter = (name: string) => !q || name.toLowerCase().includes(q)
  const visibleBuckets = buckets.filter(
    b => matchesFilter(b.name) && (showHidden || !hiddenBuckets.has(b.name)),
  )
  const hiddenCount = buckets.filter(b => hiddenBuckets.has(b.name)).length

  return (
    <aside className="w-full h-full flex flex-col bg-zinc-950 border-r border-zinc-800">
      {/* 헤더 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
        <span className="text-xs font-medium text-zinc-400">버킷 탐색기</span>
        {state.connection.connected && (
          <button
            onClick={() => {
              setBuckets([])
              setChildren(new Map())
              setExpanded(new Set())
              void loadBuckets()
            }}
            disabled={bucketLoading}
            className="p-1 rounded text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 transition-colors"
          >
            <RefreshCw size={12} className={bucketLoading ? 'animate-spin' : ''} />
          </button>
        )}
      </div>

      {/* 버킷 검색 */}
      {state.connection.connected && buckets.length > 0 && (
        <div className="px-2 py-1.5 border-b border-zinc-800/60">
          <div className="relative">
            <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-zinc-600" />
            <input
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="버킷 검색..."
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
        {!state.connection.connected ? (
          <div className="flex flex-col items-center justify-center h-32 text-zinc-600 text-xs gap-2">
            <HardDrive size={20} />
            <span>연결 후 버킷이 표시됩니다</span>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center h-32 text-red-500 text-xs gap-2 px-3">
            <AlertCircle size={16} />
            <span className="text-center">{error}</span>
            <button
              onClick={loadBuckets}
              className="text-blue-400 hover:text-blue-300 underline"
            >
              다시 시도
            </button>
          </div>
        ) : bucketLoading ? (
          <div className="flex flex-col items-center justify-center h-32 text-zinc-600 text-xs gap-2">
            <div className="w-5 h-5 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
            <span>버킷 로드 중...</span>
          </div>
        ) : buckets.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-zinc-600 text-xs gap-2">
            <HardDrive size={20} />
            <span>버킷이 없습니다</span>
          </div>
        ) : visibleBuckets.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-zinc-600 text-xs gap-2 px-3 text-center">
            <HardDrive size={20} />
            <span>{q ? '검색 결과가 없습니다' : '표시할 버킷이 없습니다'}</span>
          </div>
        ) : (
          <div>
            {visibleBuckets.map(bucket => {
              const bucketKey = `bucket::${bucket.name}`
              const isExpanded = expanded.has(bucketKey)
              const childKey = `${bucket.name}::`
              const childNodes = children.get(childKey) ?? []
              const isLoading = loading.has(childKey)
              const isSelected = state.selectedBucket === bucket.name
              const isHidden = hiddenBuckets.has(bucket.name)

              return (
                <div key={bucket.name}>
                  <div
                    onClick={() => toggleBucket(bucket.name)}
                    onContextMenu={e =>
                      openMenu(e, [
                        { label: '업로드 위치로 설정', icon: <FolderInput size={13} />, onClick: () => onSetUploadDest?.(bucket.name, '') },
                        { label: '경로 복사', icon: <Copy size={13} />, onClick: () => doCopy(bucket.name) },
                      ])
                    }
                    className={`group flex items-center gap-1.5 px-2 py-1.5 cursor-pointer text-xs transition-colors hover:bg-zinc-800 ${
                      isSelected ? 'bg-zinc-800/70 text-zinc-100' : 'text-zinc-300'
                    } ${isHidden ? 'opacity-50' : ''}`}
                  >
                    <span className="text-zinc-500">
                      {isLoading ? (
                        <div className="w-3 h-3 border border-zinc-600 border-t-zinc-400 rounded-full animate-spin" />
                      ) : isExpanded ? (
                        <ChevronDown size={13} />
                      ) : (
                        <ChevronRight size={13} />
                      )}
                    </span>
                    <HardDrive size={13} className="text-blue-400 shrink-0" />
                    <span className="truncate font-medium flex-1 min-w-0">{bucket.name}</span>
                    {bucket.region && (
                      <span className="text-[10px] text-zinc-600 shrink-0 group-hover:hidden">{bucket.region}</span>
                    )}
                    {/* 숨기기/복원 버튼 (호버 시 표시) */}
                    <button
                      onClick={e => toggleHidden(bucket.name, e)}
                      title={isHidden ? '버킷 다시 표시' : '버킷 숨기기'}
                      className="hidden group-hover:flex items-center justify-center shrink-0 text-zinc-500 hover:text-zinc-200"
                    >
                      {isHidden ? <Eye size={13} /> : <EyeOff size={13} />}
                    </button>
                  </div>

                  {isExpanded && childNodes.length > 0 && (
                    <div>{renderNodes(childNodes, bucket.name, 1)}</div>
                  )}
                  {isExpanded && childNodes.length === 0 && !isLoading && (
                    <div className="text-[11px] text-zinc-600 pl-10 py-1">비어 있음</div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* 숨긴 버킷 토글 푸터 */}
      {state.connection.connected && hiddenCount > 0 && (
        <button
          onClick={() => setShowHidden(v => !v)}
          className="flex items-center justify-center gap-1.5 px-3 py-2 border-t border-zinc-800 text-[11px] text-zinc-500 hover:text-zinc-300 hover:bg-zinc-900 transition-colors"
        >
          {showHidden ? <EyeOff size={12} /> : <Eye size={12} />}
          {showHidden ? '숨긴 버킷 가리기' : `숨긴 버킷 ${hiddenCount}개 보기`}
        </button>
      )}

      {menu && (
        <ContextMenu x={menu.x} y={menu.y} items={menu.items} onClose={() => setMenu(null)} />
      )}
      {preview && (
        <ImagePreview src={preview.src} title={preview.title} onClose={() => setPreview(null)} />
      )}
    </aside>
  )
}
