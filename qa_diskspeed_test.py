"""QA: 원격 여유공간(df 파싱) + 속도 측정(프로브) 검증."""
import socket
import tempfile
import threading
import types
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


def test_df_parse():
    """disk_space의 df -Pk 출력 파싱(가짜 ssh)."""
    class FakeSSH:
        def exec_command(self, cmd, timeout=None):
            line = "/dev/disk1s1 488245288 100000000 388245288 21% /\n"
            stdout = types.SimpleNamespace(
                read=lambda: line.encode(),
                channel=types.SimpleNamespace(recv_exit_status=lambda: 0),
            )
            return None, stdout, types.SimpleNamespace(read=lambda: b"")

    info = sftp_engine.disk_space(FakeSSH(), "/data")
    print("df 파싱:", info)
    assert info["total"] == 488245288 * 1024
    assert info["free"] == 388245288 * 1024
    assert info["used"] == info["total"] - info["free"]


def test_measure():
    root = tempfile.mkdtemp(prefix="qa-spd-root-")
    host_key = paramiko.RSAKey.generate(2048)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    port = sock.getsockname()[1]
    stop = threading.Event()
    threading.Thread(target=_serve, args=(sock, host_key, root, stop), daemon=True).start()
    try:
        ssh = sftp_engine.connect(host="127.0.0.1", port=port, username="qa", password="x", timeout=10)
        res = sftp_engine.measure_throughput(ssh, "/", size_bytes=4 * 1024 * 1024)
        print("측정:", {k: round(v) for k, v in res.items()})
        assert res["uploadBps"] > 0 and res["downloadBps"] > 0
        # 프로브 파일이 정리됐는지
        leftover = [p.name for p in Path(root).glob(".dm_speedtest_*")]
        assert not leftover, f"프로브 미삭제: {leftover}"
        ssh.close()
    finally:
        stop.set()
        sock.close()


def main():
    test_df_parse()
    test_measure()
    print("\n✅ 여유공간/속도측정 검증 통과")


if __name__ == "__main__":
    main()
