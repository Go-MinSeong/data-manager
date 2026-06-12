// WS 훅 — /api/ws/jobs/{jobId} 구독

import { useEffect, useRef, useState, useCallback } from 'react'
import type { Job, WsEvent } from '../types'
import { AUTH_TOKEN } from '../lib/api'

export interface JobProgress {
  completedFiles: number
  totalFiles: number
  transferredBytes: number
  totalBytes: number
  currentFile: string
  speedBps: number
  etaSec: number | null
}

export interface UseJobState {
  job: Job | null
  progress: JobProgress | null
  done: { success: number; failure: number; elapsedSec: number } | null
  error: string | null
  canceled: boolean
  connected: boolean
}

export function useJob(jobId: string | null) {
  const [state, setState] = useState<UseJobState>({
    job: null,
    progress: null,
    done: null,
    error: null,
    canceled: false,
    connected: false,
  })
  const wsRef = useRef<WebSocket | null>(null)

  const close = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!jobId) {
      close()
      setState({
        job: null,
        progress: null,
        done: null,
        error: null,
        canceled: false,
        connected: false,
      })
      return
    }

    // Determine ws protocol
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const tokenQs = AUTH_TOKEN ? `?token=${encodeURIComponent(AUTH_TOKEN)}` : ''
    const url = `${proto}//${host}/api/ws/jobs/${jobId}${tokenQs}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setState(s => ({ ...s, connected: true }))
    }

    ws.onmessage = (e: MessageEvent) => {
      let evt: WsEvent
      try {
        evt = JSON.parse(e.data as string) as WsEvent
      } catch {
        return
      }

      switch (evt.type) {
        case 'start':
          setState(s => ({ ...s, job: evt.job }))
          break
        case 'progress':
          setState(s => ({
            ...s,
            progress: {
              completedFiles: evt.completedFiles,
              totalFiles: evt.totalFiles,
              transferredBytes: evt.transferredBytes,
              totalBytes: evt.totalBytes,
              currentFile: evt.currentFile,
              speedBps: evt.speedBps,
              etaSec: evt.etaSec,
            },
          }))
          break
        case 'done':
          setState(s => ({
            ...s,
            done: {
              success: evt.success,
              failure: evt.failure,
              elapsedSec: evt.elapsedSec,
            },
            connected: false,
          }))
          ws.close()
          break
        case 'error':
          setState(s => ({ ...s, error: evt.message, connected: false }))
          ws.close()
          break
        case 'canceled':
          setState(s => ({ ...s, canceled: true, connected: false }))
          ws.close()
          break
        default:
          break
      }
    }

    ws.onerror = () => {
      setState(s => ({ ...s, error: 'WebSocket 연결 오류', connected: false }))
    }

    ws.onclose = () => {
      setState(s => ({ ...s, connected: false }))
    }

    return close
  }, [jobId, close])

  return { state, close }
}
