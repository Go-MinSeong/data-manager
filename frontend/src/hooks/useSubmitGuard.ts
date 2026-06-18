import { useRef, useState } from 'react'

/**
 * 중복 제출 방지 가드.
 * 느린 연결에서 요청이 응답하기 전까지 버튼이 활성으로 남아 여러 번 눌리는 것을 막는다.
 * ref로 동기적 재진입(빠른 더블클릭)을 차단하고, state로 비활성 UI를 구동한다.
 */
export function useSubmitGuard() {
  const inFlight = useRef(false)
  const [submitting, setSubmitting] = useState(false)

  const run = async (fn: () => Promise<void>) => {
    if (inFlight.current) return
    inFlight.current = true
    setSubmitting(true)
    try {
      await fn()
    } finally {
      inFlight.current = false
      setSubmitting(false)
    }
  }

  return { submitting, run }
}
