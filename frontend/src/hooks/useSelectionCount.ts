import { useState, useEffect, useRef } from 'react'

export interface SelectionCount {
  totalFiles: number
  totalBytes: number
}

/**
 * 다운로드 선택(checkedKeys)의 재귀 파일 수·바이트를 자동 계산한다.
 *
 * - 폴더(prefix, '/'로 끝남)는 flatFn으로 재귀 열거해 합산하고, 파일은 개수만 센다.
 * - 폴더별 결과를 캐시해 같은 폴더를 다시 선택해도 재열거하지 않는다(재요청 무비용).
 * - 계산은 비동기이며, 캐시된 값 + 파일 수는 즉시 부분합으로 보여주고 나머지를 채운다.
 *
 * @param cacheNamespace 캐시 네임스페이스(S3=버킷, 원격=호스트). null이면 비활성(미연결 등).
 * @param flatFn         prefix 하나의 재귀 요약을 반환. ('/' 유무는 호출측에서 정규화)
 */
export function useSelectionCount(
  checkedKeys: Set<string>,
  cacheNamespace: string | null,
  flatFn: (prefix: string) => Promise<{ totalFiles: number; totalBytes: number }>,
): { count: SelectionCount | null; loading: boolean } {
  const [count, setCount] = useState<SelectionCount | null>(null)
  const [loading, setLoading] = useState(false)
  const cache = useRef(new Map<string, SelectionCount>())

  useEffect(() => {
    if (!cacheNamespace || checkedKeys.size === 0) {
      setCount(null)
      setLoading(false)
      return
    }
    let cancelled = false
    const prefixes = [...checkedKeys].filter(k => k.endsWith('/'))
    const fileCount = [...checkedKeys].filter(k => !k.endsWith('/')).length
    const ck = (p: string) => `${cacheNamespace}|${p}`

    const sum = (): SelectionCount => {
      let tf = fileCount
      let tb = 0
      for (const p of prefixes) {
        const c = cache.current.get(ck(p))
        if (c) {
          tf += c.totalFiles
          tb += c.totalBytes
        }
      }
      return { totalFiles: tf, totalBytes: tb }
    }

    const missing = prefixes.filter(p => !cache.current.has(ck(p)))
    setCount(sum()) // 캐시된 값 + 파일 수를 즉시 표시(부분합)
    if (missing.length === 0) {
      setLoading(false)
      return
    }

    setLoading(true)
    ;(async () => {
      for (const p of missing) {
        try {
          const r = await flatFn(p)
          if (cancelled) return
          cache.current.set(ck(p), { totalFiles: r.totalFiles, totalBytes: r.totalBytes })
          setCount(sum())
        } catch {
          // 실패한 폴더는 캐시하지 않고 건너뜀(다음 선택 시 재시도)
        }
      }
      if (!cancelled) setLoading(false)
    })()

    return () => {
      cancelled = true
    }
    // flatFn은 매 렌더 새 함수라 deps에서 제외(선택/네임스페이스 변화에만 반응)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkedKeys, cacheNamespace])

  return { count, loading }
}
