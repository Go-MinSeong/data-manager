import { useState, useEffect } from 'react'
import { KeyRound, User, Plus, Trash2, ChevronDown, Wifi } from 'lucide-react'
import * as api from '../lib/api'
import { useAppStore } from '../store/appStore'
import type { Profile } from '../types'

type Mode = 'profile' | 'keys' | 'save'

export function ConnectPanel() {
  const { dispatch } = useAppStore()
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [mode, setMode] = useState<Mode>('profile')
  const [loading, setLoading] = useState(false)

  // profile mode
  const [selectedProfile, setSelectedProfile] = useState('')
  const [profileRegion, setProfileRegion] = useState('')

  // keys mode
  const [accessKeyId, setAccessKeyId] = useState('')
  const [secretAccessKey, setSecretAccessKey] = useState('')
  const [keysRegion, setKeysRegion] = useState('ap-northeast-2')

  // save mode
  const [saveName, setSaveName] = useState('')
  const [saveAccessKey, setSaveAccessKey] = useState('')
  const [saveSecretKey, setSaveSecretKey] = useState('')
  const [saveRegion, setSaveRegion] = useState('ap-northeast-2')

  const toast = (message: string, variant: 'error' | 'success' | 'info' = 'error') => {
    dispatch({
      type: 'ADD_TOAST',
      payload: { id: Date.now().toString(), message, variant },
    })
  }

  const loadProfiles = async () => {
    try {
      const res = await api.getProfiles()
      setProfiles(res.profiles)
      if (res.profiles.length > 0 && !selectedProfile) {
        setSelectedProfile(res.profiles[0].name)
        setProfileRegion(res.profiles[0].region ?? '')
      }
    } catch {
      // 백엔드 미연결 시 무시
    }
  }

  useEffect(() => {
    void loadProfiles()
  }, [])

  const handleConnect = async () => {
    setLoading(true)
    try {
      let res
      if (mode === 'profile') {
        res = await api.connect({
          mode: 'profile',
          profileName: selectedProfile,
          region: profileRegion || undefined,
        })
      } else {
        res = await api.connect({
          mode: 'keys',
          accessKeyId,
          secretAccessKey,
          region: keysRegion,
        })
      }
      if (res.ok) {
        dispatch({
          type: 'SET_CONNECTION',
          payload: { connected: true, identity: res.identity, region: res.region },
        })
        toast('AWS에 연결되었습니다.', 'success')
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
    if (!saveName || !saveAccessKey || !saveSecretKey) {
      toast('이름, 액세스 키, 시크릿 키는 필수입니다.')
      return
    }
    setLoading(true)
    try {
      await api.saveCredentials({
        name: saveName,
        accessKeyId: saveAccessKey,
        secretAccessKey: saveSecretKey,
        region: saveRegion,
      })
      toast('Keychain에 저장되었습니다.', 'success')
      setSaveName('')
      setSaveAccessKey('')
      setSaveSecretKey('')
      await loadProfiles()
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
      await api.deleteCredentials(name)
      toast('삭제되었습니다.', 'success')
      await loadProfiles()
    } catch (e) {
      toast(e instanceof Error ? e.message : '삭제 실패')
    }
  }

  return (
    <div className="flex-1 flex items-center justify-center bg-zinc-950">
      <div className="dm-stagger w-full max-w-md bg-zinc-900 rounded-xl border border-zinc-800 shadow-2xl p-6">
        <h2 className="text-lg font-semibold text-zinc-100 mb-1">AWS 연결</h2>
        <p className="text-xs text-zinc-500 mb-5">S3 버킷에 접근하려면 자격증명이 필요합니다.</p>

        {/* 모드 탭 */}
        <div className="flex gap-1 mb-5 bg-zinc-800 p-1 rounded-lg">
          {(['profile', 'keys', 'save'] as Mode[]).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`flex-1 text-xs py-1.5 rounded-md transition-colors font-medium ${
                mode === m
                  ? 'bg-zinc-700 text-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {m === 'profile' ? '프로파일' : m === 'keys' ? '직접 입력' : '새 저장'}
            </button>
          ))}
        </div>

        {mode === 'profile' && (
          <div className="space-y-3">
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">프로파일</label>
              <div className="relative">
                <select
                  value={selectedProfile}
                  onChange={e => {
                    setSelectedProfile(e.target.value)
                    const p = profiles.find(p => p.name === e.target.value)
                    setProfileRegion(p?.region ?? '')
                  }}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 appearance-none pr-8 focus:outline-none focus:border-blue-500"
                >
                  {profiles.length === 0 && (
                    <option value="">프로파일 없음</option>
                  )}
                  {profiles.map(p => (
                    <option key={p.name} value={p.name}>
                      {p.name} ({p.source === 'keychain' ? '🔑 Keychain' : '~/.aws'})
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
              </div>
            </div>
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">리전 (선택)</label>
              <input
                value={profileRegion}
                onChange={e => setProfileRegion(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && selectedProfile) void handleConnect() }}
                placeholder="ap-northeast-2"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
              />
            </div>
            {/* 저장된 프로파일 삭제 목록 */}
            {profiles.filter(p => p.source === 'keychain').length > 0 && (
              <div className="pt-2 border-t border-zinc-800">
                <p className="text-xs text-zinc-500 mb-2">Keychain 저장 프로파일</p>
                <div className="space-y-1">
                  {profiles.filter(p => p.source === 'keychain').map(p => (
                    <div key={p.name} className="flex items-center justify-between text-xs text-zinc-400">
                      <span>{p.name}</span>
                      <button
                        onClick={() => handleDelete(p.name)}
                        className="p-1 hover:text-red-400 transition-colors"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {mode === 'keys' && (
          <div className="space-y-3">
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">Access Key ID</label>
              <input
                value={accessKeyId}
                onChange={e => setAccessKeyId(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') void handleConnect() }}
                placeholder="AKIAIOSFODNN7EXAMPLE"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">Secret Access Key</label>
              <input
                type="password"
                value={secretAccessKey}
                onChange={e => setSecretAccessKey(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') void handleConnect() }}
                placeholder="••••••••••••••••••••"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">리전</label>
              <input
                value={keysRegion}
                onChange={e => setKeysRegion(e.target.value)}
                placeholder="ap-northeast-2"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
        )}

        {mode === 'save' && (
          <div className="space-y-3">
            <p className="text-xs text-zinc-500">자격증명을 macOS Keychain에 안전하게 저장합니다.</p>
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">프로파일 이름</label>
              <input
                value={saveName}
                onChange={e => setSaveName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') void handleSave() }}
                placeholder="my-profile"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">Access Key ID</label>
              <input
                value={saveAccessKey}
                onChange={e => setSaveAccessKey(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') void handleSave() }}
                placeholder="AKIAIOSFODNN7EXAMPLE"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">Secret Access Key</label>
              <input
                type="password"
                value={saveSecretKey}
                onChange={e => setSaveSecretKey(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') void handleSave() }}
                placeholder="••••••••••••••••••••"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">리전</label>
              <input
                value={saveRegion}
                onChange={e => setSaveRegion(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') void handleSave() }}
                placeholder="ap-northeast-2"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
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
                {loading ? '저장 중...' : 'Keychain에 저장'}
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
          <User size={11} />
          자격증명은 로컬 Keychain에만 저장되며 외부로 전송되지 않습니다.
        </p>
      </div>
    </div>
  )
}
