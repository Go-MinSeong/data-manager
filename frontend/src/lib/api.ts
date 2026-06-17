// API 클라이언트 — /api 엔드포인트 래퍼

import type { Profile, Job, RemoteProfile } from '../types'

const BASE = '/api'

// ── 로컬 접근 토큰 ───────────────────────────────────────────────────────────
// 셸(pywebview)이 창 URL(?t=)로만 토큰을 전달한다. 부팅 시 1회 읽어 메모리에 보관하고
// URL에서 즉시 제거(주소창/히스토리 노출 방지)한다. 이후 모든 요청 헤더에 실어 보낸다.
function readToken(): string {
  try {
    const params = new URLSearchParams(window.location.search)
    const t = params.get('t')
    if (t) {
      params.delete('t')
      const qs = params.toString()
      const clean = window.location.pathname + (qs ? `?${qs}` : '')
      window.history.replaceState({}, '', clean)
      return t
    }
  } catch {
    // ignore
  }
  return ''
}

export const AUTH_TOKEN = readToken()

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {}
  if (body) headers['Content-Type'] = 'application/json'
  if (AUTH_TOKEN) headers['X-S3M-Token'] = AUTH_TOKEN
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const json = await res.json()
      msg = json.error || json.detail || msg
    } catch {
      // ignore
    }
    const err = new Error(msg) as Error & { status?: number }
    err.status = res.status
    throw err
  }
  return res.json() as Promise<T>
}

/** 원격 연결이 끊겨 재연결이 필요한 에러인지 판별한다(409). */
export function isDisconnectError(e: unknown): boolean {
  return (
    !!e &&
    typeof e === 'object' &&
    (e as { status?: number }).status === 409
  )
}

// ── 자격증명 / 연결 ──────────────────────────────────────────────────────────

export const getProfiles = () =>
  request<{ profiles: Profile[] }>('GET', '/profiles')

export const saveCredentials = (data: {
  name: string
  accessKeyId: string
  secretAccessKey: string
  region: string
}) => request<{ ok: true }>('POST', '/credentials', data)

export const deleteCredentials = (name: string) =>
  request<{ ok: true }>('DELETE', `/credentials/${encodeURIComponent(name)}`)

export const connect = (
  body:
    | { mode: 'keys'; accessKeyId: string; secretAccessKey: string; region: string }
    | { mode: 'profile'; profileName: string; region?: string },
) =>
  request<
    | { ok: true; identity: { account: string; arn: string }; region: string }
    | { ok: false; error: string }
  >('POST', '/connect', body)

export const getConnection = () =>
  request<{
    connected: boolean
    identity?: { account: string; arn: string }
    region?: string
  }>('GET', '/connection')

export const disconnect = () =>
  request<{ ok: true }>('POST', '/disconnect')

// ── 탐색 ────────────────────────────────────────────────────────────────────

export const getBuckets = () =>
  request<{ buckets: { name: string; region: string | null }[] }>('GET', '/buckets')

export const getObjects = (bucket: string, prefix?: string) => {
  const params = new URLSearchParams({ bucket })
  if (prefix) params.set('prefix', prefix)
  return request<{
    prefix: string
    folders: import('../types').S3Folder[]
    objects: import('../types').S3Object[]
  }>('GET', `/objects?${params}`)
}

export const getFlatObjects = (bucket: string, prefix?: string) => {
  const params = new URLSearchParams({ bucket })
  if (prefix) params.set('prefix', prefix)
  return request<{ totalFiles: number; totalBytes: number }>(
    'GET',
    `/objects/flat?${params}`,
  )
}

export const getRemoteFlat = (path?: string) => {
  const qs = path ? `?path=${encodeURIComponent(path)}` : ''
  return request<{ totalFiles: number; totalBytes: number }>('GET', `/remote/flat${qs}`)
}

/** 파일 수·평균 크기로 동시 전송 수를 추천한다(작은 파일 多→높게, 큰 파일→낮게). */
export function recommendWorkers(fileCount: number, totalBytes: number): number {
  if (fileCount <= 1) return 2
  const avg = totalBytes / fileCount
  const MB = 1024 * 1024
  if (avg < 0.25 * MB) return 16
  if (avg < 4 * MB) return 10
  if (avg < 32 * MB) return 6
  if (avg < 256 * MB) return 4
  return 2
}

// ── 전송 작업 ────────────────────────────────────────────────────────────────

export const startDownload = (body: {
  bucket: string
  prefixes?: string[]
  keys?: string[]
  localDir: string
  maxWorkers?: number
}) => request<{ jobId: string }>('POST', '/download', body)

export const startUpload = (body: {
  bucket: string
  prefix: string
  localPaths: string[]
  maxWorkers?: number
}) => request<{ jobId: string }>('POST', '/upload', body)

// ── 원격(SFTP) 서버 ───────────────────────────────────────────────────────────

export const getRemoteProfiles = () =>
  request<{ profiles: RemoteProfile[] }>('GET', '/remote/profiles')

export const saveRemoteProfile = (data: {
  name: string
  host: string
  port: number
  username: string
  authType: 'key' | 'password'
  keyPath?: string | null
  secret?: string
}) => request<{ ok: true }>('POST', '/remote/profiles', data)

export const deleteRemoteProfile = (name: string) =>
  request<{ ok: true }>('DELETE', `/remote/profiles/${encodeURIComponent(name)}`)

export const remoteConnect = (
  body:
    | { mode: 'profile'; profileName: string }
    | {
        mode: 'adhoc'
        host: string
        port?: number
        username: string
        authType: 'key' | 'password'
        keyPath?: string | null
        secret?: string
      },
) =>
  request<
    | {
        ok: true
        host: string
        username: string
        homeDir: string
        defaultPath?: string | null
        profileName?: string | null
      }
    | { ok: false; error: string }
  >('POST', '/remote/connect', body)

export const getRemoteConnection = () =>
  request<{
    connected: boolean
    host?: string
    username?: string
    homeDir?: string
    defaultPath?: string | null
    profileName?: string | null
  }>('GET', '/remote/connection')

export const setRemoteDefaultPath = (name: string, path: string | null) =>
  request<{ ok: true }>(
    'POST',
    `/remote/profiles/${encodeURIComponent(name)}/default-path`,
    { path },
  )

export const getRemoteDiskSpace = (path?: string) => {
  const qs = path ? `?path=${encodeURIComponent(path)}` : ''
  return request<{ total: number; free: number; used: number }>('GET', `/remote/diskspace${qs}`)
}

export const getLocalDiskSpace = (path?: string) => {
  const qs = path ? `?path=${encodeURIComponent(path)}` : ''
  return request<{ total: number; free: number; used: number }>('GET', `/local/diskspace${qs}`)
}

export const measureRemote = (path?: string) =>
  request<{ uploadBps: number; downloadBps: number; sizeBytes: number }>(
    'POST',
    '/remote/measure',
    { path },
  )

export const remoteDisconnect = () =>
  request<{ ok: true }>('POST', '/remote/disconnect')

export const getRemoteObjects = (path?: string) => {
  const params = new URLSearchParams()
  if (path) params.set('path', path)
  const qs = params.toString()
  return request<{
    prefix: string
    folders: import('../types').S3Folder[]
    objects: import('../types').S3Object[]
  }>('GET', `/remote/objects${qs ? `?${qs}` : ''}`)
}

export const startRemoteDownload = (body: {
  remoteDirs?: string[]
  keys?: string[]
  localDir: string
  maxWorkers?: number
}) => request<{ jobId: string }>('POST', '/remote/download', body)

export const startRemoteUpload = (body: {
  remoteDir: string
  localPaths: string[]
  maxWorkers?: number
}) => request<{ jobId: string }>('POST', '/remote/upload', body)

// ── S3 ↔ 원격 전송 ────────────────────────────────────────────────────────────

export const startS3ToRemote = (body: {
  bucket: string
  prefixes?: string[]
  keys?: string[]
  remoteDir: string
  maxWorkers?: number
}) => request<{ jobId: string }>('POST', '/transfer/s3-to-remote', body)

export const startRemoteToS3 = (body: {
  remoteDirs?: string[]
  keys?: string[]
  bucket: string
  prefix?: string
  maxWorkers?: number
}) => request<{ jobId: string }>('POST', '/transfer/remote-to-s3', body)

export const startRemoteToRemote = (body: {
  srcDirs?: string[]
  srcKeys?: string[]
  destDir: string
  maxWorkers?: number
}) => request<{ jobId: string }>('POST', '/transfer/remote-to-remote', body)

// ── 두 번째 원격(remote-b) — 원격↔원격 대상 ────────────────────────────────────

export const remoteBConnect = (
  body:
    | { mode: 'profile'; profileName: string }
    | {
        mode: 'adhoc'; host: string; port?: number; username: string
        authType: 'key' | 'password'; keyPath?: string | null; secret?: string
      },
) =>
  request<
    | { ok: true; host: string; username: string; homeDir: string }
    | { ok: false; error: string }
  >('POST', '/remote-b/connect', body)

export const getRemoteBConnection = () =>
  request<{ connected: boolean; host?: string; username?: string; homeDir?: string }>(
    'GET',
    '/remote-b/connection',
  )

export const remoteBDisconnect = () => request<{ ok: true }>('POST', '/remote-b/disconnect')

export const getRemoteBObjects = (path?: string) => {
  const qs = path ? `?path=${encodeURIComponent(path)}` : ''
  return request<{
    prefix: string
    folders: import('../types').S3Folder[]
    objects: import('../types').S3Object[]
  }>('GET', `/remote-b/objects${qs}`)
}

export const getRemoteBDiskSpace = (path?: string) => {
  const qs = path ? `?path=${encodeURIComponent(path)}` : ''
  return request<{ total: number; free: number; used: number }>('GET', `/remote-b/diskspace${qs}`)
}

// ── 잡 ────────────────────────────────────────────────────────────────────────

export const getJobs = () => request<{ jobs: Job[] }>('GET', '/jobs')

export const getJob = (jobId: string) => request<Job>('GET', `/jobs/${jobId}`)

export const cancelJob = (jobId: string) =>
  request<{ ok: true }>('POST', `/jobs/${jobId}/cancel`)

// ── 로컬 / 시스템 ─────────────────────────────────────────────────────────────

export const pickFolder = () =>
  request<{ path: string | null }>('POST', '/pick-folder')

export const pickFiles = () =>
  request<{ paths: string[] }>('POST', '/pick-files')

export const revealInFinder = (path: string) =>
  request<{ ok: boolean }>('POST', '/reveal', { path })

export const getHealth = () =>
  request<{ ok: true; version: string }>('GET', '/health')

// ── 환경설정 ──────────────────────────────────────────────────────────────────

export const getPreferences = () =>
  request<{ hiddenBuckets: string[]; lastDownloadDir: string }>('GET', '/preferences')

export const setHiddenBuckets = (hiddenBuckets: string[]) =>
  request<{ hiddenBuckets: string[] }>('PUT', '/preferences/hidden-buckets', { hiddenBuckets })
