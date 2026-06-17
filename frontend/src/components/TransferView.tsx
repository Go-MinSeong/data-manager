import { useState, useEffect } from 'react'
import {
  ArrowLeftRight, Cloud, Server, Send, HardDrive, Gauge,
  History, Wifi, LogOut, ChevronDown,
} from 'lucide-react'
import * as api from '../lib/api'
import { useAppStore } from '../store/appStore'
import { useJob } from '../hooks/useJob'
import { JobProgress } from './JobProgress'
import { TreeSidebar } from './TreeSidebar'
import { RemoteTreeSidebar } from './RemoteTreeSidebar'
import { RemoteFolderBrowser } from './RemoteFolderBrowser'
import { JobsPanel } from './JobsPanel'
import { formatBytes, formatSpeed } from './ProgressBar'
import type { RemoteProfile } from '../types'

type Direction = 's3-to-remote' | 'remote-to-s3' | 'remote-to-remote'

interface BConn { connected: boolean; host?: string; username?: string; homeDir?: string }

const DIRECTIONS: { id: Direction; label: string }[] = [
  { id: 's3-to-remote', label: 'S3 → 원격' },
  { id: 'remote-to-s3', label: '원격 → S3' },
  { id: 'remote-to-remote', label: '원격 → 원격' },
]

export function TransferView() {
  const { state, dispatch } = useAppStore()
  const s3Connected = state.connection.connected
  const remoteConnected = state.remoteConnection.connected

  const [direction, setDirection] = useState<Direction>('s3-to-remote')
  const [checkedKeys, setCheckedKeys] = useState<Set<string>>(new Set())
  const [selectedRemoteDir, setSelectedRemoteDir] = useState('')
  const [remoteDir, setRemoteDir] = useState('')      // 목적지(기본 원격) — s3-to-remote
  const [remoteTouched, setRemoteTouched] = useState(false)
  const [destBucket, setDestBucket] = useState('')    // 목적지(S3) — remote-to-s3
  const [destPrefix, setDestPrefix] = useState('')
  const [destBDir, setDestBDir] = useState('')        // 목적지(원격B) — remote-to-remote
  const [maxWorkers, setMaxWorkers] = useState(4)
  const [jobId, setJobId] = useState<string | null>(null)
  const { state: jobState, close: closeJob } = useJob(jobId)

  const [freeSpace, setFreeSpace] = useState<number | null>(null)
  const [measuring, setMeasuring] = useState(false)
  const [speed, setSpeed] = useState<{ up: number; down: number } | null>(null)
  const [tab, setTab] = useState<'transfer' | 'jobs'>('transfer')
  const [transferBytes, setTransferBytes] = useState<number | null>(null)

  // 두 번째 원격(대상) 연결
  const [bConn, setBConn] = useState<BConn>({ connected: false })
  const [bProfiles, setBProfiles] = useState<RemoteProfile[]>([])
  const [selectedBProfile, setSelectedBProfile] = useState('')
  const [bConnecting, setBConnecting] = useState(false)

  const toast = (message: string, variant: 'error' | 'success' | 'info' = 'error') => {
    dispatch({ type: 'ADD_TOAST', payload: { id: Date.now().toString(), message, variant } })
  }

  const srcIsS3 = direction === 's3-to-remote'

  useEffect(() => { setCheckedKeys(new Set()); setTransferBytes(null) }, [direction])

  // 대상 서버(B) 상태·프로파일 로드
  useEffect(() => {
    api.getRemoteBConnection().then(setBConn).catch(() => { /* 무시 */ })
    api.getRemoteProfiles()
      .then(r => {
        setBProfiles(r.profiles)
        if (r.profiles.length && !selectedBProfile) setSelectedBProfile(r.profiles[0].name)
      })
      .catch(() => { /* 무시 */ })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 목적지(기본 원격) 경로 기본값 = 홈/선택 폴더
  useEffect(() => {
    if (remoteTouched) return
    if (selectedRemoteDir) setRemoteDir(selectedRemoteDir)
    else if (state.remoteConnection.homeDir) setRemoteDir(state.remoteConnection.homeDir)
  }, [selectedRemoteDir, state.remoteConnection.homeDir, remoteTouched])

  // 목적지(원격B) 경로 기본값 = B 홈
  useEffect(() => {
    if (bConn.connected && bConn.homeDir && !destBDir) setDestBDir(bConn.homeDir)
  }, [bConn, destBDir])

  // 목적지가 원격일 때 여유 공간 조회
  useEffect(() => {
    let cancelled = false
    const set = (v: number | null) => { if (!cancelled) setFreeSpace(v) }
    if (direction === 's3-to-remote' && remoteConnected && remoteDir) {
      api.getRemoteDiskSpace(remoteDir).then(r => set(r.free)).catch(() => set(null))
    } else if (direction === 'remote-to-remote' && bConn.connected && destBDir) {
      api.getRemoteBDiskSpace(destBDir).then(r => set(r.free)).catch(() => set(null))
    } else {
      set(null)
    }
    return () => { cancelled = true }
  }, [direction, remoteDir, destBDir, remoteConnected, bConn.connected])

  const connectB = async () => {
    if (!selectedBProfile) { toast('대상 프로파일을 선택하세요.'); return }
    setBConnecting(true)
    try {
      const res = await api.remoteBConnect({ mode: 'profile', profileName: selectedBProfile })
      if (res.ok) {
        setBConn({ connected: true, host: res.host, username: res.username, homeDir: res.homeDir })
        setDestBDir(res.homeDir)
        toast(`대상 ${res.username}@${res.host} 연결됨`, 'success')
      } else {
        toast(res.error)
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : '대상 연결 실패')
    } finally {
      setBConnecting(false)
    }
  }

  const disconnectB = async () => {
    try { await api.remoteBDisconnect() } catch { /* ignore */ }
    setBConn({ connected: false })
    setDestBDir('')
  }

  const handleMeasure = async () => {
    setMeasuring(true)
    setSpeed(null)
    try {
      const r = await api.measureRemote(direction === 's3-to-remote' ? remoteDir : undefined)
      setSpeed({ up: r.uploadBps, down: r.downloadBps })
    } catch (e) {
      toast(e instanceof Error ? e.message : '속도 측정 실패')
    } finally {
      setMeasuring(false)
    }
  }

  const handleRecommend = async () => {
    if (checkedKeys.size === 0) { toast('전송할 항목을 먼저 선택하세요.'); return }
    try {
      let tf = 0
      let tb = 0
      const folders = [...checkedKeys].filter(k => k.endsWith('/'))
      const files = [...checkedKeys].filter(k => !k.endsWith('/'))
      tf = files.length
      if (srcIsS3) {
        if (!state.selectedBucket) { toast('소스 버킷을 선택하세요.'); return }
        for (const p of folders) {
          const r = await api.getFlatObjects(state.selectedBucket, p)
          tf += r.totalFiles; tb += r.totalBytes
        }
      } else {
        for (const d of folders) {
          const r = await api.getRemoteFlat(d.replace(/\/$/, ''))
          tf += r.totalFiles; tb += r.totalBytes
        }
      }
      setTransferBytes(tb)
      setMaxWorkers(api.recommendWorkers(tf, tb))
      toast('파일 수·크기에 맞춰 동시 수를 추천했습니다.', 'info')
    } catch (e) {
      toast(e instanceof Error ? e.message : '추천 계산 실패')
    }
  }

  const isRunning = jobId && !jobState.done && !jobState.error && !jobState.canceled

  // 연결 가드 (방향별 필요 연결)
  const needsS3 = direction !== 'remote-to-remote'
  if ((needsS3 && !s3Connected) || !remoteConnected) {
    const missing: string[] = []
    if (needsS3 && !s3Connected) missing.push('S3')
    if (!remoteConnected) missing.push('원격 서버')
    return (
      <div className="flex-1 flex items-center justify-center bg-zinc-950">
        <div className="text-center max-w-sm">
          <ArrowLeftRight size={28} className="mx-auto text-zinc-600 mb-3" />
          <p className="text-sm text-zinc-300 mb-1">전송하려면 연결이 필요합니다</p>
          <p className="text-xs text-zinc-500 mb-4">미연결: <span className="text-zinc-300">{missing.join(', ')}</span></p>
          <div className="flex gap-2 justify-center">
            {needsS3 && !s3Connected && (
              <button onClick={() => dispatch({ type: 'SET_MODE', payload: 's3' })}
                className="flex items-center gap-1.5 px-3 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-xs text-zinc-200">
                <Cloud size={13} /> S3 연결하기
              </button>
            )}
            {!remoteConnected && (
              <button onClick={() => dispatch({ type: 'SET_MODE', payload: 'remote' })}
                className="flex items-center gap-1.5 px-3 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-xs text-zinc-200">
                <Server size={13} /> 원격 연결하기
              </button>
            )}
          </div>
          <div className="mt-4">
            <DirectionPicker direction={direction} onChange={setDirection} />
          </div>
        </div>
      </div>
    )
  }

  const handleTransfer = async () => {
    if (checkedKeys.size === 0) { toast('전송할 항목을 선택하세요.'); return }
    const folders = [...checkedKeys].filter(k => k.endsWith('/'))
    const files = [...checkedKeys].filter(k => !k.endsWith('/'))
    closeJob()
    setJobId(null)
    try {
      let res
      if (direction === 's3-to-remote') {
        if (!state.selectedBucket) { toast('소스 버킷을 선택하세요 (왼쪽 트리에서 버킷 펼치기).'); return }
        if (!remoteDir) { toast('대상 원격 경로를 선택하세요.'); return }
        res = await api.startS3ToRemote({
          bucket: state.selectedBucket,
          prefixes: folders.length ? folders : undefined,
          keys: files.length ? files : undefined,
          remoteDir, maxWorkers,
        })
      } else if (direction === 'remote-to-s3') {
        if (!destBucket) { toast('대상 S3 버킷을 입력하세요.'); return }
        res = await api.startRemoteToS3({
          remoteDirs: folders.length ? folders.map(d => d.replace(/\/$/, '')) : undefined,
          keys: files.length ? files : undefined,
          bucket: destBucket, prefix: destPrefix, maxWorkers,
        })
      } else {
        if (!bConn.connected) { toast('대상 원격 서버에 연결하세요.'); return }
        if (!destBDir) { toast('대상 원격 경로를 선택하세요.'); return }
        res = await api.startRemoteToRemote({
          srcDirs: folders.length ? folders.map(d => d.replace(/\/$/, '')) : undefined,
          srcKeys: files.length ? files : undefined,
          destDir: destBDir, maxWorkers,
        })
      }
      setJobId(res.jobId)
      toast('전송을 시작했습니다.', 'success')
    } catch (e) {
      if (api.isDisconnectError(e)) { toast('연결이 끊겼습니다. 연결 상태를 확인하세요.'); return }
      toast(e instanceof Error ? e.message : '전송 시작 실패')
    }
  }

  return (
    <div className="flex flex-col flex-1 min-w-0 bg-zinc-900">
      {/* 탭 */}
      <div className="flex gap-0.5 px-3 pt-3 border-b border-zinc-800 shrink-0">
        {([['transfer', '전송', <ArrowLeftRight size={14} />], ['jobs', '작업 이력', <History size={14} />]] as const).map(
          ([id, label, icon]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-t-lg transition-colors -mb-px ${
                tab === id ? 'bg-zinc-800 text-zinc-100 border border-b-zinc-800 border-zinc-700'
                  : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50 border border-transparent'}`}>
              {icon}{label}
            </button>
          ),
        )}
      </div>

      {tab === 'jobs' ? (
        <div className="flex-1 overflow-y-auto"><JobsPanel /></div>
      ) : (
        <>
          {/* 방향 선택 */}
          <div className="flex items-center gap-3 px-4 py-2.5 border-b border-zinc-800 shrink-0">
            <span className="text-xs text-zinc-500">방향</span>
            <DirectionPicker direction={direction} onChange={setDirection} />
          </div>

          <div className="flex flex-1 min-h-0">
            {/* 소스 트리 */}
            <div className="w-72 shrink-0 h-full min-h-0 border-r border-zinc-800">
              {srcIsS3 ? (
                <TreeSidebar checkedKeys={checkedKeys} onCheckedChange={setCheckedKeys} />
              ) : (
                <RemoteTreeSidebar
                  checkedKeys={checkedKeys}
                  onCheckedChange={setCheckedKeys}
                  onSelectDir={setSelectedRemoteDir}
                  selectedDir={selectedRemoteDir}
                />
              )}
            </div>

            {/* 설정 패널 */}
            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              <h3 className="text-sm font-semibold text-zinc-200">
                {DIRECTIONS.find(d => d.id === direction)?.label} 전송
              </h3>

              {/* 선택된 항목 */}
              <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-3">
                <span className="text-xs text-zinc-400 block mb-1">선택된 항목 ({checkedKeys.size})</span>
                {checkedKeys.size === 0 ? (
                  <p className="text-xs text-zinc-600">왼쪽 {srcIsS3 ? 'S3' : '원격'} 트리에서 파일/폴더를 선택하세요</p>
                ) : (
                  <div className="space-y-0.5">
                    {[...checkedKeys].slice(0, 6).map(k => (
                      <p key={k} className="text-xs text-zinc-300 font-mono truncate">{k}</p>
                    ))}
                    {checkedKeys.size > 6 && <p className="text-xs text-zinc-500">... 외 {checkedKeys.size - 6}개</p>}
                  </div>
                )}
              </div>

              {/* 목적지 */}
              {direction === 's3-to-remote' && (
                <DestRemote
                  label="대상 원격 경로 (폴더 선택)"
                  value={remoteDir}
                  onChange={p => { setRemoteDir(p); setRemoteTouched(true) }}
                  freeSpace={freeSpace}
                  transferBytes={transferBytes}
                />
              )}
              {direction === 'remote-to-s3' && (
                <div className="space-y-3">
                  <div>
                    <label className="text-xs text-zinc-400 mb-1 block">대상 S3 버킷</label>
                    <input value={destBucket} onChange={e => setDestBucket(e.target.value)} placeholder="my-bucket"
                      className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500" />
                  </div>
                  <div>
                    <label className="text-xs text-zinc-400 mb-1 block">대상 Prefix (선택)</label>
                    <input value={destPrefix} onChange={e => setDestPrefix(e.target.value)} placeholder="backups/2026/"
                      className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500" />
                  </div>
                  <p className="flex items-center gap-1.5 text-[11px] text-zinc-500"><HardDrive size={11} /> S3 — 용량 제한 없음</p>
                </div>
              )}
              {direction === 'remote-to-remote' && (
                <div className="space-y-2">
                  {/* 대상 서버 연결 */}
                  <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-3">
                    <label className="text-xs text-zinc-400 mb-1.5 block">대상 원격 서버</label>
                    {bConn.connected ? (
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-emerald-400 flex items-center gap-1.5">
                          <Wifi size={12} /> {bConn.username}@{bConn.host}
                        </span>
                        <button onClick={disconnectB} className="flex items-center gap-1 text-[11px] text-zinc-500 hover:text-zinc-200">
                          <LogOut size={11} /> 해제
                        </button>
                      </div>
                    ) : (
                      <div className="flex gap-2">
                        <div className="relative flex-1">
                          <select value={selectedBProfile} onChange={e => setSelectedBProfile(e.target.value)}
                            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 appearance-none pr-8 focus:outline-none focus:border-blue-500">
                            {bProfiles.length === 0 && <option value="">저장된 프로파일 없음</option>}
                            {bProfiles.map(p => (
                              <option key={p.name} value={p.name}>{p.name} ({p.username}@{p.host})</option>
                            ))}
                          </select>
                          <ChevronDown size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
                        </div>
                        <button onClick={connectB} disabled={bConnecting || !selectedBProfile}
                          className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-xs font-medium px-3 rounded-lg">
                          <Wifi size={13} /> {bConnecting ? '연결 중' : '연결'}
                        </button>
                      </div>
                    )}
                  </div>
                  {bConn.connected && (
                    <DestRemote
                      label="대상 원격 경로 (폴더 선택)"
                      value={destBDir}
                      onChange={setDestBDir}
                      fetcher={api.getRemoteBObjects}
                      freeSpace={freeSpace}
                      transferBytes={transferBytes}
                    />
                  )}
                </div>
              )}

              {/* 링크 속도 측정 (Mac ↔ 소스 원격) */}
              {!srcIsS3 || direction === 's3-to-remote' ? (
                <div className="flex items-center gap-3">
                  <button onClick={handleMeasure} disabled={measuring}
                    className="flex items-center gap-1.5 text-xs text-zinc-300 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 px-2.5 py-1.5 rounded-lg transition-colors">
                    <Gauge size={13} className={measuring ? 'animate-pulse' : ''} />
                    {measuring ? '측정 중...' : '링크 속도 측정'}
                  </button>
                  {speed && (
                    <span className="text-[11px] text-zinc-400">
                      ↑ {formatSpeed(speed.up)} · ↓ {formatSpeed(speed.down)} <span className="text-zinc-600">(Mac↔원격)</span>
                    </span>
                  )}
                </div>
              ) : null}

              {/* 동시 전송 수 */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs text-zinc-400">동시 전송 수</label>
                  <div className="flex items-center gap-2">
                    <button onClick={handleRecommend} disabled={checkedKeys.size === 0}
                      className="text-[11px] text-blue-400 hover:text-blue-300 disabled:text-zinc-600">추천</button>
                    <span className="text-xs text-zinc-200 font-medium">{maxWorkers}</span>
                  </div>
                </div>
                <input type="range" min={1} max={16} value={maxWorkers}
                  onChange={e => setMaxWorkers(Number(e.target.value))} className="w-full accent-blue-500" />
              </div>

              <button onClick={handleTransfer} disabled={!!isRunning || checkedKeys.size === 0}
                className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium py-2.5 rounded-lg transition-colors">
                <Send size={15} /> 전송 시작
              </button>

              <p className="text-[11px] text-zinc-600">
                {direction === 'remote-to-remote'
                  ? '서버끼리 직접 연결하지 않고 이 컴퓨터를 경유합니다(허용 IP 안전).'
                  : '가능하면 원격 서버가 S3와 직접 주고받고(빠름), 안 되면 자동으로 이 컴퓨터를 경유합니다.'}
              </p>

              {jobId && (
                <JobProgress jobId={jobId} jobState={jobState} onDismiss={() => { setJobId(null); closeJob() }} />
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// 방향 선택 세그먼트
function DirectionPicker({ direction, onChange }: { direction: Direction; onChange: (d: Direction) => void }) {
  return (
    <div className="flex gap-0.5 bg-zinc-800 p-0.5 rounded-lg">
      {DIRECTIONS.map(d => (
        <button key={d.id} onClick={() => onChange(d.id)}
          className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-md transition-colors ${
            direction === d.id ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-400 hover:text-zinc-200'}`}>
          {d.label}
        </button>
      ))}
    </div>
  )
}

// 원격 목적지(폴더 브라우저 + 여유공간)
function DestRemote({
  label, value, onChange, fetcher, freeSpace, transferBytes,
}: {
  label: string
  value: string
  onChange: (p: string) => void
  fetcher?: (path?: string) => Promise<{ prefix: string; folders: { key: string; name: string }[] }>
  freeSpace: number | null
  transferBytes: number | null
}) {
  return (
    <div>
      <label className="text-xs text-zinc-400 mb-1 block">{label}</label>
      <RemoteFolderBrowser value={value} onChange={onChange} fetcher={fetcher} />
      <div className="flex items-center gap-3 mt-1.5 text-[11px] text-zinc-500">
        <span className="flex items-center gap-1.5">
          <HardDrive size={11} /> 여유 공간:{' '}
          {freeSpace == null ? '—' : <span className="text-zinc-300">{formatBytes(freeSpace)}</span>}
        </span>
        {transferBytes != null && freeSpace != null && transferBytes > freeSpace && (
          <span className="text-amber-400">⚠ 공간 부족 가능 (전송 {formatBytes(transferBytes)})</span>
        )}
      </div>
    </div>
  )
}
