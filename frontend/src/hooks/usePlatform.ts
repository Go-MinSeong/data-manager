import { useState, useEffect } from 'react'
import * as api from '../lib/api'

/**
 * 셸이 실행 중인 OS를 알려준다(플랫폼별 UI 조정용).
 *
 * macOS 전용인 것: 신호등(창 버튼) 자리 왼쪽 여백, 헤더 드래그 영역
 * (Windows 는 네이티브 타이틀바를 그대로 쓰므로 둘 다 불필요).
 * 단축키 표기도 ⌘ / Ctrl 로 갈린다.
 *
 * 조회 전에는 macOS 로 가정한다(기존 동작 유지).
 */
export function usePlatform(): { isMac: boolean; modKey: string } {
  const [isMac, setIsMac] = useState(true)

  useEffect(() => {
    let cancelled = false
    api.getHealth()
      .then(h => {
        if (!cancelled && h.platform) setIsMac(h.platform !== 'win32')
      })
      .catch(() => { /* 조회 실패 시 기본값(macOS) 유지 */ })
    return () => { cancelled = true }
  }, [])

  return { isMac, modKey: isMac ? '⌘' : 'Ctrl' }
}
