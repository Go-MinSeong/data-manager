"""QA: SFTP 채널 재사용 검증 (MaxSessions 'Connect failed' 회귀 방지).

파일마다 새 SFTP 채널을 열던 버그를 수정했음을 검증한다.
ssh.open_sftp 호출 수를 세어, 다운로드 시 채널 수가 '파일 수'가 아니라
'워커 수(+목록용 1개)'에 비례하는지 확인한다.
"""
import socket
import tempfile
import threading
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
    root = tempfile.mkdtemp(prefix="qa-chan-root-")
    Path(root, "data").mkdir()
    n_files = 20
    for i in range(n_files):
        Path(root, "data", f"f{i:02d}.bin").write_bytes(bytes([i % 256]) * 1024)

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

        # open_sftp 호출 횟수 계측
        opens = {"n": 0}
        real_open = ssh.open_sftp
        lock = threading.Lock()

        def counting_open():
            with lock:
                opens["n"] += 1
            return real_open()

        ssh.open_sftp = counting_open

        max_workers = 3
        dl = tempfile.mkdtemp(prefix="qa-chan-dl-")
        s, f = sftp_engine.download_files(
            ssh, dl, remote_dirs=["/data"], max_workers=max_workers
        )
        print(f"파일 {n_files}개 다운로드: 성공 {s} 실패 {f} | open_sftp 호출 {opens['n']}회")

        # 정확성
        assert (s, f) == (n_files, 0), (s, f)
        for i in range(n_files):
            assert Path(dl, "data", f"f{i:02d}.bin").read_bytes() == bytes([i % 256]) * 1024

        # 핵심: 채널 수가 파일 수에 비례하지 않고 워커 수(+목록 1)에 묶여야 한다.
        # list_all_files 1개 + 전송 워커 채널 max_workers개 = 4개 이하.
        assert opens["n"] <= max_workers + 1, (
            f"채널이 너무 많이 열림({opens['n']}) — 파일별 재생성 회귀 의심"
        )

        ssh.close()
        print("\n✅ 채널 재사용 검증 통과 (파일 20개를 채널 ≤4개로 처리)")
    finally:
        stop.set()
        sock.close()


if __name__ == "__main__":
    main()
