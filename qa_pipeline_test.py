"""QA: 잡 매니저 + WebSocket 이벤트 파이프라인 E2E 검증.

AWS 자격증명 없이 s3_engine 전송 함수를 시뮬레이션으로 교체하여
submit_download → start/file/progress/done 이벤트가 큐로 올바르게 흐르는지 확인한다.
"""
import asyncio
import time

from s3manager.core import jobs as jobs_module
from s3manager.core.jobs import job_manager


def fake_download(s3_client, bucket, local_dir, *, prefix=None, keys=None,
                  max_workers=5, on_bytes=None, on_file=None, cancel_event=None):
    """실제 다운로드 대신 진행률 콜백을 시뮬레이션."""
    files = ["a.txt", "b.txt", "c.txt"]
    for f in files:
        if cancel_event and cancel_event.is_set():
            break
        for _ in range(5):
            on_bytes(2048)
            time.sleep(0.05)  # throttle(0.2s) 효과 확인용
        on_file(f"{prefix}{f}", True, None)
    return len(files), 0


async def main():
    loop = asyncio.get_running_loop()
    job_manager.set_event_loop(loop)
    # 전송 함수 교체
    jobs_module.s3_engine.download_objects = fake_download

    job_id = job_manager.submit_download(
        s3_client=object(), bucket="b", local_dir="/tmp/qa-down",
        prefix="folder/", max_workers=3,
    )
    q = job_manager.subscribe(job_id)
    assert q is not None, "subscribe 실패"

    received = []
    deadline = loop.time() + 10
    while loop.time() < deadline:
        try:
            ev = await asyncio.wait_for(q.get(), timeout=2)
        except asyncio.TimeoutError:
            break
        received.append(ev)
        if ev.get("type") in ("done", "error", "canceled"):
            break

    types = [e.get("type") for e in received]
    print("이벤트 시퀀스:", types)

    job = job_manager.get_job(job_id)
    print("최종 잡 상태:", job.status, "| localDir:", repr(job.local_dir),
          "| completed:", job.completed_files, "| failed:", job.failed_files)

    # 검증 — start는 WS 연결 시 스냅샷(job.to_dict)이 흡수하므로
    # 구독 타이밍에 따라 누락될 수 있음(계약 §3 설계). progress/file/done 흐름과 종료를 본다.
    assert "file" in types, "file 이벤트 없음"
    assert "progress" in types, "progress 이벤트 없음(throttle 동작 확인)"
    assert types[-1] == "done", f"마지막 이벤트가 done이 아님: {types}"
    assert job.status == "done"
    assert job.completed_files == 3
    assert job.local_dir == "/tmp/qa-down", f"localDir 미기록: {job.local_dir}"

    # 취소 경로 검증
    jobs_module.s3_engine.download_objects = fake_download
    job_id2 = job_manager.submit_download(
        s3_client=object(), bucket="b", local_dir="/tmp/qa2", prefix="x/", max_workers=1,
    )
    q2 = job_manager.subscribe(job_id2)
    await asyncio.sleep(0.1)
    job_manager.cancel_job(job_id2)
    types2 = []
    deadline = loop.time() + 8
    while loop.time() < deadline:
        try:
            ev = await asyncio.wait_for(q2.get(), timeout=2)
        except asyncio.TimeoutError:
            break
        types2.append(ev.get("type"))
        if ev.get("type") in ("done", "error", "canceled"):
            break
    print("취소 시퀀스:", types2, "| 상태:", job_manager.get_job(job_id2).status)
    assert job_manager.get_job(job_id2).status == "canceled", "취소 미반영"

    print("\n✅ 잡/WS 파이프라인 E2E 통과")


if __name__ == "__main__":
    asyncio.run(main())
