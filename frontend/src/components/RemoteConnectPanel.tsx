import { useState, useEffect } from 'react'
import type { KeyboardEvent } from 'react'
import { KeyRound, Server, Plus, Trash2, ChevronDown, Wifi, RefreshCw } from 'lucide-react'
import * as api from '../lib/api'
import type { ProfileHealth } from '../lib/api'
import { useAppStore } from '../store/appStore'
import type { RemoteProfile } from '../types'

type Mode = 'profile' | 'adhoc' | 'save'
type AuthType = 'key' | 'password'

export function RemoteConnectPanel() {
  const { dispatch } = useAppStore()
  const [profiles, setProfiles] = useState<RemoteProfile[]>([])
  const [mode, setMode] = useState<Mode>('profile')
  const [loading, setLoading] = useState(false)
  const [health, setHealth] = useState<Record<string, ProfileHealth>>({})
  const [checking, setChecking] = useState(false)

  // profile mode
  const [selectedProfile, setSelectedProfile] = useState('')

  // 공유 입력 필드 (adhoc / save)
  const [host, setHost] = useState('')
  const [port, setPort] = useState(22)
  const [username, setUsername] = useState('')
  const [authType, setAuthType] = useState<AuthType>('key')
  const [keyPath, setKeyPath] = useState('')
  const [secret, setSecret] = useState('')
  const [saveName, setSaveName] = useState('')

  const toast = (message: string, variant: 'error' | 'success' | 'info' = 'error') => {
    dispatch({ type: 'ADD_TOAST', payload: { id: Date.now().toString(), message, variant } })
  }

  const loadProfiles = async () => {
    try {
      const res = await api.getRemoteProfiles()
      setProfiles(res.profiles)
      if (res.profiles.length > 0 && !selectedProfile) {
        setSelectedProfile(res.profiles[0].name)
      }
    } catch {
      // 백엔드 미연결 시 무시
    }
  }

  const loadHealth = async () => {
    setChecking(true)
    try {
      const res = await api.getProfileHealth()
      const map: Record<string, ProfileHealth> = {}
      for (const r of res.results) map[r.name] = r
      setHealth(map)
    } catch {
      // 점검 실패는 무시(미표시 상태로 둠)
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => {
    void loadProfiles()
    void loadHealth()
  }, [])

  const applyConnection = (res: {
    host: string
    username: string
    homeDir: string
    defaultPath?: string | null
    profileName?: string | null
  }) => {
    dispatch({
      type: 'SET_REMOTE_CONNECTION',
      payload: {
        connected: true,
        host: res.host,
        username: res.username,
        homeDir: res.homeDir,
        defaultPath: res.defaultPath ?? null,
        profileName: res.profileName ?? null,
      },
    })
    toast(`${res.username}@${res.host}에 연결되었습니다.`, 'success')
  }

  const handleConnect = async () => {
    setLoading(true)
    try {
      let res
      if (mode === 'profile') {
        if (!selectedProfile) {
          toast('프로파일을 선택하세요.')
          return
        }
        res = await api.remoteConnect({ mode: 'profile', profileName: selectedProfile })
      } else {
        if (!host || !username) {
          toast('호스트와 사용자명은 필수입니다.')
          return
        }
        res = await api.remoteConnect({
          mode: 'adhoc',
          host,
          port,
          username,
          authType,
          keyPath: authType === 'key' ? keyPath || null : null,
          secret: secret || undefined,
        })
      }
      if (res.ok) {
        applyConnection(res)
      } else {
        toast(res.error)
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : '연결 실패')
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    if (!saveName || !host || !username) {
      toast('이름, 호스트, 사용자명은 필수입니다.')
      return
    }
    setLoading(true)
    try {
      await api.saveRemoteProfile({
        name: saveName,
        host,
        port,
        username,
        authType,
        keyPath: authType === 'key' ? keyPath || null : null,
        secret: secret || undefined,
      })
      toast('프로파일을 저장했습니다.', 'success')
      setSaveName('')
      setSecret('')
      await loadProfiles()
      setSelectedProfile(saveName)
      setMode('profile')
    } catch (e) {
      toast(e instanceof Error ? e.message : '저장 실패')
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`'${name}' 프로파일을 삭제하시겠습니까?`)) return
    try {
      await api.deleteRemoteProfile(name)
      toast('삭제되었습니다.', 'success')
      await loadProfiles()
    } catch (e) {
      toast(e instanceof Error ? e.message : '삭제 실패')
    }
  }

  // adhoc / save 가 공유하는 입력 폼
  const renderFields = (withName: boolean, onSubmit: () => void) => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Enter') onSubmit() }
    return (
    <div className="space-y-3">
      {withName && (
        <div>
          <label className="text-xs text-zinc-400 mb-1 block">프로파일 이름</label>
          <input
            value={saveName}
            onChange={e => setSaveName(e.target.value)}
            onKeyDown={onKey}
            placeholder="my-server"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
          />
        </div>
      )}
      <div className="flex gap-2">
        <div className="flex-1">
          <label className="text-xs text-zinc-400 mb-1 block">호스트</label>
          <input
            value={host}
            onChange={e => setHost(e.target.value)}
            onKeyDown={onKey}
            placeholder="example.com"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
          />
        </div>
        <div className="w-20">
          <label className="text-xs text-zinc-400 mb-1 block">포트</label>
          <input
            type="number"
            value={port}
            onChange={e => setPort(Number(e.target.value) || 22)}
            onKeyDown={onKey}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>
      <div>
        <label className="text-xs text-zinc-400 mb-1 block">사용자명</label>
        <input
          value={username}
          onChange={e => setUsername(e.target.value)}
          onKeyDown={onKey}
          placeholder="ubuntu"
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
        />
      </div>
      <div>
        <label className="text-xs text-zinc-400 mb-1 block">인증 방식</label>
        <div className="flex gap-1 bg-zinc-800 p-1 rounded-lg">
          {(['key', 'password'] as AuthType[]).map(a => (
            <button
              key={a}
              onClick={() => setAuthType(a)}
              className={`flex-1 text-xs py-1.5 rounded-md transition-colors font-medium ${
                authType === a ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {a === 'key' ? 'SSH 키' : '비밀번호'}
            </button>
          ))}
        </div>
      </div>
      {authType === 'key' && (
        <div>
          <label className="text-xs text-zinc-400 mb-1 block">키 파일 경로 (선택)</label>
          <input
            value={keyPath}
            onChange={e => setKeyPath(e.target.value)}
            onKeyDown={onKey}
            placeholder="~/.ssh/id_ed25519 (비우면 기본 키·ssh-agent 사용)"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
          />
        </div>
      )}
      <div>
        <label className="text-xs text-zinc-400 mb-1 block">
          {authType === 'key' ? '키 passphrase (선택)' : '비밀번호'}
        </label>
        <input
          type="password"
          value={secret}
          onChange={e => setSecret(e.target.value)}
          onKeyDown={onKey}
          placeholder="••••••••"
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
        />
      </div>
    </div>
    )
  }

  return (
    <div className="flex-1 flex items-center justify-center bg-zinc-950">
      <div className="dm-stagger w-full max-w-md bg-zinc-900 rounded-xl border border-zinc-800 shadow-2xl p-6">
        <h2 className="text-lg font-semibold text-zinc-100 mb-1">원격 서버 연결</h2>
        <p className="text-xs text-zinc-500 mb-5">SFTP(SSH)로 원격 서버에 접속합니다.</p>

        {/* 모드 탭 */}
        <div className="flex gap-1 mb-5 bg-zinc-800 p-1 rounded-lg">
          {(['profile', 'adhoc', 'save'] as Mode[]).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`flex-1 text-xs py-1.5 rounded-md transition-colors font-medium ${
                mode === m ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {m === 'profile' ? '프로파일' : m === 'adhoc' ? '직접 입력' : '새 저장'}
            </button>
          ))}
        </div>

        {mode === 'profile' && (
          <div className="space-y-3">
            <div>
              <label className="text-xs text-zinc-400 mb-1 flex items-center gap-1.5">
                프로파일
                {checking && (
                  <RefreshCw size={11} className="animate-spin text-zinc-500" />
                )}
              </label>
              <div className="relative">
                <select
                  value={selectedProfile}
                  onChange={e => setSelectedProfile(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 appearance-none pr-8 focus:outline-none focus:border-blue-500"
                >
                  {profiles.length === 0 && <option value="">프로파일 없음</option>}
                  {profiles.map(p => (
                    <option key={p.name} value={p.name}>
                      {p.name} ({p.username}@{p.host}:{p.port})
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
              </div>
            </div>
            {profiles.length > 0 && (
              <div className="pt-2 border-t border-zinc-800">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs text-zinc-500">저장된 프로파일</p>
                  <button
                    onClick={() => void loadHealth()}
                    disabled={checking}
                    title="연결 가능 여부 다시 점검"
                    className="flex items-center gap-1 text-[11px] text-zinc-500 hover:text-zinc-300 disabled:opacity-50 transition-colors"
                  >
                    <RefreshCw size={11} className={checking ? 'animate-spin' : ''} />
                    점검
                  </button>
                </div>
                <div className="space-y-1">
                  {profiles.map(p => {
                    const h = health[p.name]
                    const dot = !h
                      ? 'bg-zinc-600'
                      : h.reachable
                        ? 'bg-emerald-500'
                        : 'bg-red-500'
                    const dotTitle = !h
                      ? '미점검'
                      : h.reachable
                        ? `연결 가능${h.latencyMs != null ? ` · ${h.latencyMs}ms` : ''}`
                        : '연결 불가 (서버 꺼짐·IP 차단·포트 닫힘)'
                    return (
                      <div key={p.name} className="flex items-center justify-between text-xs text-zinc-400">
                        <span className="truncate flex items-center gap-1.5">
                          <span
                            className={`w-2 h-2 rounded-full shrink-0 ${dot}`}
                            title={dotTitle}
                          />
                          {p.name}
                          <span className="text-zinc-600 ml-0.5">
                            {p.username}@{p.host} · {p.authType === 'key' ? '🔑' : '••'}
                          </span>
                        </span>
                        <button
                          onClick={() => handleDelete(p.name)}
                          className="p-1 hover:text-red-400 transition-colors shrink-0"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {mode === 'adhoc' && renderFields(false, () => void handleConnect())}
        {mode === 'save' && (
          <>
            <p className="text-xs text-zinc-500 mb-3">
              접속 정보를 저장합니다. 비밀(passphrase/비밀번호)은 macOS Keychain에만 보관됩니다.
            </p>
            {renderFields(true, () => void handleSave())}
          </>
        )}

        <div className="mt-5 flex gap-2">
          {mode !== 'save' ? (
            <>
              <button
                onClick={handleConnect}
                disabled={loading || (mode === 'profile' && !selectedProfile)}
                className="flex-1 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium py-2.5 rounded-lg transition-[background-color,scale] duration-150 active:scale-[0.96]"
              >
                {loading ? (
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <Wifi size={15} />
                )}
                {loading ? '연결 중...' : '연결'}
              </button>
              <button
                onClick={() => setMode('save')}
                className="px-3 py-2.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 rounded-lg transition-colors"
                title="새 프로파일 저장"
              >
                <Plus size={15} />
              </button>
            </>
          ) : (
            <>
              <button
                onClick={handleSave}
                disabled={loading}
                className="flex-1 flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-700 text-white text-sm font-medium py-2.5 rounded-lg transition-[background-color,scale] duration-150 active:scale-[0.96]"
              >
                {loading ? (
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <KeyRound size={15} />
                )}
                {loading ? '저장 중...' : '프로파일 저장'}
              </button>
              <button
                onClick={() => setMode('profile')}
                className="px-3 py-2.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-400 rounded-lg transition-colors text-sm"
              >
                취소
              </button>
            </>
          )}
        </div>

        <p className="text-xs text-zinc-600 text-center mt-3 flex items-center justify-center gap-1">
          <Server size={11} />
          접속 정보는 로컬에만 저장되며 비밀은 Keychain에 보관됩니다.
        </p>
      </div>
    </div>
  )
}
