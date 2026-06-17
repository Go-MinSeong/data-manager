import { useState, useEffect } from 'react'
import { ArrowRight, ArrowLeftRight, Cloud, Server, Send } from 'lucide-react'
import * as api from '../lib/api'
import { useAppStore } from '../store/appStore'
import { useJob } from '../hooks/useJob'
import { JobProgress } from './JobProgress'
import { TreeSidebar } from './TreeSidebar'
import { RemoteTreeSidebar } from './RemoteTreeSidebar'

type Direction = 's3-to-remote' | 'remote-to-s3'

export function TransferView() {
  const { state, dispatch } = useAppStore()
  const s3Connected = state.connection.connected
  const remoteConnected = state.remoteConnection.connected

  const [direction, setDirection] = useState<Direction>('s3-to-remote')
  const [checkedKeys, setCheckedKeys] = useState<Set<string>>(new Set())
  const [selectedRemoteDir, setSelectedRemoteDir] = useState('')
  const [remoteDir, setRemoteDir] = useState('')   // 목적지(원격) 경로 (s3-to-remote)
  const [remoteTouched, setRemoteTouched] = useState(false)
  const [destBucket, setDestBucket] = useState('') // 목적지(S3) 버킷 (remote-to-s3)
  const [destPrefix, setDestPrefix] = useState('')
  const [maxWorkers, setMaxWorkers] = useState(4)
  const [jobId, setJobId] = useState<string | null>(null)
  const { state: jobState, close: closeJob } = useJob(jobId)

  const toast = (message: string, variant: 'error' | 'success' | 'info' = 'error') => {
    dispatch({ type: 'ADD_TOAST', payload: { id: Date.now().toString(), message, variant } })
  }

  // 방향 바뀌면 선택 초기화
  useEffect(() => { setCheckedKeys(new Set()) }, [direction])

  // 원격 목적지 기본값 = 원격 홈 (사용자가 수정 전까지), 또는 트리에서 고른 폴더
  useEffect(() => {
    if (remoteTouched) return
    if (selectedRemoteDir) setRemoteDir(selectedRemoteDir)
    else if (state.remoteConnection.homeDir) setRemoteDir(state.remoteConnection.homeDir)
  }, [selectedRemoteDir, state.remoteConnection.homeDir, remoteTouched])

  const isRunning = jobId && !jobState.done && !jobState.error && !jobState.canceled

  // 연결 가드
  if (!s3Connected || !remoteConnected) {
    const missing: string[] = []
    if (!s3Connected) missing.push('S3')
    if (!remoteConnected) missing.push('원격 서버')
    return (
      <div className="flex-1 flex items-center justify-center bg-zinc-950">
        <div className="text-center max-w-sm">
          <ArrowLeftRight size={28} className="mx-auto text-zinc-600 mb-3" />
          <p className="text-sm text-zinc-300 mb-1">전송하려면 양쪽 모두 연결해야 합니다</p>
          <p className="text-xs text-zinc-500 mb-4">
            미연결: <span className="text-zinc-300">{missing.join(', ')}</span>
          </p>
          <div className="flex gap-2 justify-center">
            {!s3Connected && (
              <button
                onClick={() => dispatch({ type: 'SET_MODE', payload: 's3' })}
                className="flex items-center gap-1.5 px-3 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-xs text-zinc-200"
              >
                <Cloud size={13} /> S3 연결하기
              </button>
            )}
            {!remoteConnected && (
              <button
                onClick={() => dispatch({ type: 'SET_MODE', payload: 'remote' })}
                className="flex items-center gap-1.5 px-3 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-xs text-zinc-200"
              >
                <Server size={13} /> 원격 연결하기
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  const handleTransfer = async () => {
    if (checkedKeys.size === 0) {
      toast('전송할 항목을 선택하세요.')
      return
    }
    closeJob()
    setJobId(null)
    try {
      let res
      if (direction === 's3-to-remote') {
        if (!state.selectedBucket) {
          toast('소스 버킷을 선택하세요 (왼쪽 트리에서 버킷 펼치기).')
          return
        }
        if (!remoteDir) {
          toast('대상 원격 경로를 입력하세요.')
          return
        }
        const prefixes = [...checkedKeys].filter(k => k.endsWith('/'))
        const keys = [...checkedKeys].filter(k => !k.endsWith('/'))
        res = await api.startS3ToRemote({
          bucket: state.selectedBucket,
          prefixes: prefixes.length ? prefixes : undefined,
          keys: keys.length ? keys : undefined,
          remoteDir,
          maxWorkers,
        })
      } else {
        if (!destBucket) {
          toast('대상 S3 버킷을 입력하세요.')
          return
        }
        const dirs = [...checkedKeys].filter(k => k.endsWith('/')).map(d => d.replace(/\/$/, ''))
        const keys = [...checkedKeys].filter(k => !k.endsWith('/'))
        res = await api.startRemoteToS3({
          remoteDirs: dirs.length ? dirs : undefined,
          keys: keys.length ? keys : undefined,
          bucket: destBucket,
          prefix: destPrefix,
          maxWorkers,
        })
      }
      setJobId(res.jobId)
      toast('전송을 시작했습니다.', 'success')
    } catch (e) {
      if (api.isDisconnectError(e)) {
        // 어느 쪽 세션이 끊겼는지 정확히 알 수 없으므로 양쪽 상태 재조회 유도
        toast('연결이 끊겼습니다. 연결 상태를 확인하세요.')
        return
      }
      toast(e instanceof Error ? e.message : '전송 시작 실패')
    }
  }

  const srcIsS3 = direction === 's3-to-remote'

  return (
    <div className="flex flex-col flex-1 min-w-0 bg-zinc-900">
      {/* 방향 토글 */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-zinc-800 shrink-0">
        <span className="text-xs text-zinc-500">방향</span>
        <div className="flex items-center gap-2 text-xs">
          <span className={`flex items-center gap-1 font-medium ${srcIsS3 ? 'text-blue-400' : 'text-emerald-400'}`}>
            {srcIsS3 ? <Cloud size={13} /> : <Server size={13} />}
            {srcIsS3 ? 'S3' : '원격'}
          </span>
          <ArrowRight size={14} className="text-zinc-500" />
          <span className={`flex items-center gap-1 font-medium ${srcIsS3 ? 'text-emerald-400' : 'text-blue-400'}`}>
            {srcIsS3 ? <Server size={13} /> : <Cloud size={13} />}
            {srcIsS3 ? '원격' : 'S3'}
          </span>
        </div>
        <button
          onClick={() => setDirection(d => (d === 's3-to-remote' ? 'remote-to-s3' : 's3-to-remote'))}
          className="ml-2 flex items-center gap-1 text-xs text-zinc-400 hover:text-zinc-100 px-2 py-1 rounded hover:bg-zinc-800 transition-colors"
        >
          <ArrowLeftRight size={12} /> 방향 바꾸기
        </button>
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
            {srcIsS3 ? 'S3 → 원격 전송' : '원격 → S3 전송'}
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
          {srcIsS3 ? (
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">대상 원격 경로</label>
              <input
                value={remoteDir}
                onChange={e => { setRemoteDir(e.target.value); setRemoteTouched(true) }}
                placeholder="/home/user/incoming"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
              />
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <label className="text-xs text-zinc-400 mb-1 block">대상 S3 버킷</label>
                <input
                  value={destBucket}
                  onChange={e => setDestBucket(e.target.value)}
                  placeholder="my-bucket"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="text-xs text-zinc-400 mb-1 block">대상 Prefix (선택)</label>
                <input
                  value={destPrefix}
                  onChange={e => setDestPrefix(e.target.value)}
                  placeholder="backups/2026/"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>
          )}

          {/* 동시 전송 수 */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-zinc-400">동시 전송 수</label>
              <span className="text-xs text-zinc-200 font-medium">{maxWorkers}</span>
            </div>
            <input
              type="range" min={1} max={16} value={maxWorkers}
              onChange={e => setMaxWorkers(Number(e.target.value))}
              className="w-full accent-blue-500"
            />
          </div>

          <button
            onClick={handleTransfer}
            disabled={!!isRunning || checkedKeys.size === 0}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium py-2.5 rounded-lg transition-colors"
          >
            <Send size={15} />
            전송 시작
          </button>

          <p className="text-[11px] text-zinc-600">
            가능하면 원격 서버가 S3와 직접 주고받고(빠름), 안 되면 자동으로 이 컴퓨터를 경유합니다.
          </p>

          {jobId && (
            <JobProgress
              jobId={jobId}
              jobState={jobState}
              onDismiss={() => { setJobId(null); closeJob() }}
            />
          )}
        </div>
      </div>
    </div>
  )
}
