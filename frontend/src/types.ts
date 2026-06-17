// § 1. 데이터 모델 — API_CONTRACT.md 기준

export interface Profile {
  name: string
  source: 'aws' | 'keychain'
  region: string | null
}

export interface S3Object {
  key: string
  size: number
  lastModified: string
  isFolder: false
}

export interface S3Folder {
  key: string
  name: string
  isFolder: true
}

export type S3Item = S3Object | S3Folder

export type JobKind =
  | 'download'
  | 'upload'
  | 'sync'
  | 'remote-download'
  | 'remote-upload'
  | 's3-to-remote'
  | 'remote-to-s3'
export type JobStatus = 'pending' | 'running' | 'done' | 'error' | 'canceled'

export interface Job {
  jobId: string
  kind: JobKind
  localDir: string
  status: JobStatus
  totalFiles: number
  completedFiles: number
  failedFiles: number
  totalBytes: number
  transferredBytes: number
  startedAt: string | null
  finishedAt: string | null
  error: string | null
}

// WebSocket 이벤트
export type WsEvent =
  | { type: 'start'; job: Job }
  | {
      type: 'progress'
      completedFiles: number
      totalFiles: number
      transferredBytes: number
      totalBytes: number
      currentFile: string
      speedBps: number
      etaSec: number | null
    }
  | { type: 'file'; key: string; status: 'done' | 'failed'; error?: string }
  | { type: 'done'; success: number; failure: number; elapsedSec: number }
  | { type: 'error'; message: string }
  | { type: 'canceled' }

// 연결 상태
export interface ConnectionState {
  connected: boolean
  identity?: { account: string; arn: string }
  region?: string
}

// 데이터 소스 모드 (S3 / 원격 SFTP 서버 / 전송)
export type SourceMode = 's3' | 'remote' | 'transfer'

// 원격(SFTP) 서버 프로파일 (비밀 미포함)
export interface RemoteProfile {
  name: string
  host: string
  port: number
  username: string
  authType: 'key' | 'password'
  keyPath: string | null
}

// 원격 연결 상태
export interface RemoteConnectionState {
  connected: boolean
  host?: string
  username?: string
  homeDir?: string
}

// 트리 노드
export interface TreeNode {
  key: string
  name: string
  isFolder: boolean
  size?: number
  lastModified?: string
  children?: TreeNode[]
  loaded?: boolean
  expanded?: boolean
  checked?: boolean
  indeterminate?: boolean
}

// 탭
export type PanelTab = 'download' | 'upload' | 'jobs'
