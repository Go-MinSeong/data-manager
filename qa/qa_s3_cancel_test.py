"""QA: S3 대형 파일 다운로드 취소가 즉시 먹는지 검증(회귀 방지).

이전 구현은 download_file(s3transfer)에 맡기고 진행률 콜백에서 예외를 던져
취소했다. 콜백은 데이터가 읽힐 때만 호출되므로 커넥션 대기·응답 대기 구간에서는
취소가 관측되지 않아 "안 멈추거나 한참 뒤에 멈추는" 문제가 있었다.
지금은 get_object 스트림을 청크 루프로 읽으며 청크마다 취소를 확인한다.

검증:
  1. 전송 도중 취소하면 파일 끝까지 읽지 않고 곧바로 멈춘다.
  2. 잘린 파일이 정상 파일처럼 남지 않는다(.part 정리, 최종 경로 미생성).
  3. 취소 시 남은 대기 항목이 '실패'로 무더기 집계되지 않는다.
"""
import tempfile
import threading
import time
from pathlib import Path

from s3manager.core import s3_engine

TOTAL = 200 * 1024 * 1024  # 200MB — 끝까지 읽으면 테스트가 확연히 느려진다


class _SlowBody:
    """read() 마다 조금씩 반환하는 가짜 S3 스트림(네트워크 지연 흉내)."""

    def __init__(self, total: int):
        self.remaining = total
        self.reads = 0
        self.closed = False

    def read(self, n: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        time.sleep(0.01)  # 청크당 지연
        size = min(n if n and n > 0 else 65536, self.remaining)
        self.remaining -= size
        self.reads += 1
        return b"\0" * size

    def close(self) -> None:
        self.closed = True


class _FakeS3:
    def __init__(self):
        self.body = _SlowBody(TOTAL)

    def get_object(self, Bucket=None, Key=None):  # noqa: N803
        return {"Body": self.body}


def main():
    out = Path(tempfile.mkdtemp(prefix="qa-s3cancel-")) / "big.bin"
    client = _FakeS3()
    cancel = threading.Event()
    got = {"bytes": 0}

    def on_bytes(n: int) -> None:
        got["bytes"] += n

    # 0.3초 뒤 취소
    threading.Timer(0.3, cancel.set).start()

    t0 = time.monotonic()
    ok = s3_engine.download_single(
        client, "b", "big.bin", str(out), on_bytes=on_bytes, cancel_event=cancel
    )
    elapsed = time.monotonic() - t0

    assert ok is False, "취소됐는데 성공으로 반환됨"
    assert elapsed < 3.0, f"취소가 즉시 반영되지 않음({elapsed:.1f}s)"
    assert got["bytes"] < TOTAL, "전체를 다 받아버림(취소 미동작)"
    assert not out.exists(), "잘린 파일이 최종 경로에 남았다"
    assert not Path(str(out) + ".part").exists(), ".part 임시 파일이 정리되지 않음"
    assert client.body.closed, "응답 스트림이 닫히지 않음"

    # 취소 시 대기 항목이 무더기 '실패'로 집계되지 않는지
    cancel2 = threading.Event()
    cancel2.set()
    reported: list = []
    s, f = s3_engine.download_objects(
        _FakeS3(),
        "b",
        str(out.parent),
        keys=[f"k{i}.bin" for i in range(500)],
        max_workers=4,
        on_file=lambda k, ok_, e: reported.append(k),
        cancel_event=cancel2,
    )
    assert f == 0 and s == 0, f"취소인데 성공/실패로 집계됨 (성공 {s}, 실패 {f})"
    assert len(reported) == 0, f"취소인데 {len(reported)}건이 파일 결과로 보고됨"

    mb = got["bytes"] / 1024 / 1024
    print(f"취소까지 {elapsed:.2f}s | 수신 {mb:.1f}MB / 전체 {TOTAL/1024/1024:.0f}MB")
    print("잔여 파일 없음, 스트림 닫힘, 취소 시 실패 무더기 집계 없음")
    print("\n✅ S3 대형 파일 취소 검증 통과")


if __name__ == "__main__":
    main()
