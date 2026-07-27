"""QA: SFTP 워커 파일별 재시도 + 죽은 채널 재연결 검증.

대용량/대량 전송에서 일시적 실패로 파일이 통째로 실패하던 문제를 수정했음을 검증한다.
_run_with_channel_pool 을 가짜 ssh/op 로 직접 구동해:
  1. 일시적으로 2번 실패 후 성공하는 파일이 최종 '성공'으로 계상되는지,
  2. 실패할 때마다 채널을 재연결(open_sftp 재호출)하는지,
  3. 계속 실패하는 파일은 재시도(3회) 후 '실패'로 계상되는지 확인한다.
"""
import threading

from s3manager.core import sftp_engine


class _FakeChannel:
    def close(self):
        pass


class _FakeSSH:
    """open_sftp 호출 횟수를 세는 가짜 SSHClient."""

    def __init__(self):
        self.open_calls = 0
        self._lock = threading.Lock()

    def open_sftp(self):
        with self._lock:
            self.open_calls += 1
        return _FakeChannel()


def main():
    ssh = _FakeSSH()
    attempts: dict[str, int] = {}
    lock = threading.Lock()

    # "flaky" 는 2번 실패 후 성공, "bad" 는 항상 실패, 나머지는 즉시 성공
    def op(sftp, payload):
        key = payload
        with lock:
            attempts[key] = attempts.get(key, 0) + 1
            n = attempts[key]
        if key == "flaky" and n <= 2:
            raise OSError("일시적 오류")
        if key == "bad":
            raise OSError("영구 오류")
        return True

    work = [("ok1", "ok1"), ("flaky", "flaky"), ("bad", "bad"), ("ok2", "ok2")]
    results: list[tuple[str, bool]] = []

    def on_file(key, ok, err):
        results.append((key, ok))

    # 워커 1개(채널 1개)로 결정적 검증
    success, failure = sftp_engine._run_with_channel_pool(
        ssh, work, op, max_workers=1, on_file=on_file, cancel_event=None
    )

    rmap = dict(results)
    assert success == 3, f"성공 기대 3, 실제 {success}"
    assert failure == 1, f"실패 기대 1, 실제 {failure}"
    assert rmap["flaky"] is True, "flaky 는 재시도 후 성공해야 함"
    assert rmap["bad"] is False, "bad 는 최종 실패여야 함"
    assert attempts["flaky"] == 3, f"flaky 시도 3회 기대, 실제 {attempts['flaky']}"
    assert attempts["bad"] == 3, f"bad 시도 3회(RETRIES) 기대, 실제 {attempts['bad']}"

    # 채널 재연결: 초기 1개 + (flaky 2회 실패 + bad 2회 실패)=4회 재연결 = 총 5회
    assert ssh.open_calls == 5, f"open_sftp 5회 기대, 실제 {ssh.open_calls}"

    print(f"성공 {success} 실패 {failure} | 시도 {attempts} | open_sftp {ssh.open_calls}회")
    print("\n✅ 워커 재시도 + 채널 재연결 검증 통과")


if __name__ == "__main__":
    main()
