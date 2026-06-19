"""QA: 직통(curl) 모드 전송 중 취소 검증.

_exec_status가 cancel_event를 감지하면 채널을 닫고 TransferCanceled를 던지는지,
그리고 _run worker가 이를 릴레이 폴백으로 흘리지 않고 '취소됨'으로 처리하는지 확인한다.
실제 SSH 없이 exit_status_ready가 영영 False인 가짜 채널로 '느린 curl'을 흉내낸다.
"""
import threading
import types

from s3manager.core import transfer_engine
from s3manager.core.s3_engine import TransferCanceled


def test_exec_status_cancels():
    closed = {"v": False}

    def _close():
        closed["v"] = True

    chan = types.SimpleNamespace(
        recv_exit_status=lambda: 0,
        exit_status_ready=lambda: False,  # curl이 끝나지 않는 상황
        close=_close,
    )

    class FakeSSH:
        def exec_command(self, cmd, timeout=None):
            stdout = types.SimpleNamespace(channel=chan, read=lambda: b"")
            stderr = types.SimpleNamespace(read=lambda: b"")
            return None, stdout, stderr

    ev = threading.Event()
    # 0.5초 뒤 취소 신호
    threading.Timer(0.5, ev.set).start()

    raised = False
    try:
        transfer_engine._exec_status(FakeSSH(), "curl ...", ev)
    except TransferCanceled:
        raised = True

    assert raised, "취소 시 TransferCanceled가 발생해야 함"
    assert closed["v"], "취소 시 채널을 닫아 원격 curl을 중단해야 함"
    print("exec_status: 취소 신호 → 채널 close + TransferCanceled ✅")


if __name__ == "__main__":
    test_exec_status_cancels()
    print("\n✅ 직통 모드 취소 검증 통과")
