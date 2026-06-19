"""QA: 원격 → 원격 릴레이 전송 검증 (인메모리 SFTP 서버 2개)."""
import socket
import tempfile
import threading
from pathlib import Path

import paramiko

from s3manager.core import transfer_engine, sftp_engine
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


def _spawn(root):
    host_key = paramiko.RSAKey.generate(2048)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    port = sock.getsockname()[1]
    stop = threading.Event()
    threading.Thread(target=_serve, args=(sock, host_key, root, stop), daemon=True).start()
    return port, sock, stop


def main():
    # 소스 서버 A
    root_a = tempfile.mkdtemp(prefix="qa-r2r-A-")
    Path(root_a, "proj").mkdir()
    Path(root_a, "proj", "a.txt").write_bytes(b"A" * 4096)
    Path(root_a, "proj", "sub").mkdir()
    Path(root_a, "proj", "sub", "b.txt").write_bytes(b"B" * 2048)
    Path(root_a, "note.txt").write_bytes(b"N" * 100)
    # 대상 서버 B (빈 상태)
    root_b = tempfile.mkdtemp(prefix="qa-r2r-B-")

    pa, sa, st_a = _spawn(root_a)
    pb, sb, st_b = _spawn(root_b)
    try:
        ssh_a = sftp_engine.connect(host="127.0.0.1", port=pa, username="qa", password="x", timeout=10)
        ssh_b = sftp_engine.connect(host="127.0.0.1", port=pb, username="qa", password="x", timeout=10)

        recv = {"n": 0}
        s, f = transfer_engine.remote_to_remote(
            ssh_a, ssh_b,
            src_dirs=["/proj"], src_keys=["/note.txt"], dest_dir="/incoming",
            on_bytes=lambda n: recv.__setitem__("n", recv["n"] + n),
        )
        print("원격→원격 성공/실패:", s, f, "| on_bytes:", recv["n"])
        # proj(a.txt + sub/b.txt) + note.txt = 3건
        assert (s, f) == (3, 0), (s, f)
        # 폴더명 보존
        assert Path(root_b, "incoming", "proj", "a.txt").read_bytes() == b"A" * 4096
        assert Path(root_b, "incoming", "proj", "sub", "b.txt").read_bytes() == b"B" * 2048
        assert Path(root_b, "incoming", "note.txt").read_bytes() == b"N" * 100
        assert recv["n"] == 4096 + 2048 + 100

        ssh_a.close()
        ssh_b.close()
        print("\n✅ 원격→원격 릴레이 전송 검증 통과")
    finally:
        st_a.set(); st_b.set(); sa.close(); sb.close()


if __name__ == "__main__":
    main()
