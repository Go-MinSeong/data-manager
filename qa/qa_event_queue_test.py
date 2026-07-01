"""QA: 이벤트 큐 오버플로우 처리 검증 (서버 마비 회귀 방지).

대량 전송 시 느린/끊긴 WebSocket 구독자의 큐(maxsize=500)가 가득 차면
put_nowait 가 이벤트 루프 콜백 안에서 QueueFull 을 던져 예외가 폭주하고
서버 전체가 무응답이 되던 버그를 수정했음을 검증한다.

_safe_put 이:
  1. 가득 찬 큐에서도 예외를 던지지 않고,
  2. 가장 오래된 이벤트를 버려 큐를 유계로 유지하며,
  3. 최신 이벤트를 넣는지 확인한다.
"""
import asyncio

from s3manager.core.jobs import JobManager


def main():
    q: asyncio.Queue = asyncio.Queue(maxsize=3)
    for i in range(3):
        q.put_nowait({"seq": i})
    assert q.full()

    # 가득 찬 상태에서 새 이벤트 push — 예외 없이 drop-oldest
    JobManager._safe_put(q, {"seq": 99})
    assert q.qsize() == 3, f"큐 크기 유계 실패: {q.qsize()}"

    drained = [q.get_nowait() for _ in range(3)]
    seqs = [e["seq"] for e in drained]
    assert seqs == [1, 2, 99], f"drop-oldest 기대 [1,2,99], 실제 {seqs}"

    # 여러 번 반복해도 계속 유계 + 예외 없음
    for i in range(1000):
        JobManager._safe_put(q, {"seq": i})
    assert q.qsize() == 3

    print(f"큐 유계 유지({q.qsize()}), drop-oldest 순서 {seqs}, 1000회 push 무예외")
    print("\n✅ 이벤트 큐 오버플로우 처리 검증 통과")


if __name__ == "__main__":
    main()
