"""QA: 전송 중 취소가 진행 중인 큰 파일도 즉시 중단하는지 검증.

인메모리 SFTP 서버에서 큰 파일 다운로드를 시작하고, 일정 바이트 수신 후
cancel_event를 세팅해 get()이 파일 끝까지 가지 않고 중단되는지 확인한다.
(S3는 동일한 콜백-예외 패턴을 사용한다.)
"""
import socket
import tempfile
import threading
import time
from pathlib import Path

import paramiko

from s3manager.core import sftp_engine
from qa_sftp_test import _Server, _make_stub


def _serve(sock, host_key, root, stop):
    sock.settimeout(1.0)
    while not stop.is_set():
        try:
            conn, _ = sock.accept()
        except (socket.timeout, OSError):
            continue
        t = paramiko.Transport(conn)
        t.add_server_key(host_key)
        t.set_subsystem_handler("sftp", paramiko.SFTPServer, _make_stub(root))
        try:
            t.start_server(server=_Server())
        except Exception:
            continue


def main():
    root = tempfile.mkdtemp(prefix="qa-cancel-root-")
    Path(root, "big").mkdir()
    big_size = 20 * 1024 * 1024  # 20MB
    Path(root, "big", "f.bin").write_bytes(b"Z" * big_size)

    host_key = paramiko.RSAKey.generate(2048)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    port = sock.getsockname()[1]
    stop = threading.Event()
    threading.Thread(target=_serve, args=(sock, host_key, root, stop), daemon=True).start()

    try:
        ssh = sftp_engine.connect(
            host="127.0.0.1", port=port, username="qa", password="x", timeout=10
        )

        cancel_event = threading.Event()
        recv = {"n": 0}

        def on_bytes(n):
            recv["n"] += n
            if recv["n"] >= 1 * 1024 * 1024:  # 1MB 받으면 취소
                cancel_event.set()

        dl = tempfile.mkdtemp(prefix="qa-cancel-dl-")
        t0 = time.monotonic()
        s, f = sftp_engine.download_files(
            ssh, dl, remote_dirs=["/big"],
            on_bytes=on_bytes, cancel_event=cancel_event,
        )
        elapsed = time.monotonic() - t0
        print(f"성공 {s} 실패 {f} | 수신 {recv['n'] // 1024}KB / 전체 {big_size // 1024}KB | {elapsed:.2f}s")

        # 취소되었으니 성공 0건, 수신량이 전체보다 훨씬 적어야 함(중간 중단 증거)
        assert s == 0, f"취소됐는데 성공 처리됨: {s}"
        assert recv["n"] < big_size // 2, f"중간 중단 실패 — 거의 다 받음({recv['n']})"

        ssh.close()
        print("\n✅ 전송 중 취소(중간 중단) 검증 통과")
    finally:
        stop.set()
        sock.close()


if __name__ == "__main__":
    main()
