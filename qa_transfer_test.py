"""QA: S3 ↔ 원격 전송(릴레이 경로) 검증.

인메모리 SFTP 스텁 + 가짜 S3 클라이언트로 transfer_engine의 릴레이(Mac 스트리밍 중계)
경로를 검증한다. 직통(presigned+curl)은 실제 S3/원격 환경이 필요해 여기선 강제로
릴레이 모드로 돌린다(remote_can_reach_s3를 False로 패치).
"""
import io
import socket
import tempfile
import threading
import types
from pathlib import Path

import paramiko

from s3manager.core import transfer_engine
from qa_sftp_test import _Server, _make_stub


class FakeS3:
    """relay 경로가 쓰는 최소 S3 API만 구현(get_object/upload_fileobj)."""

    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.meta = types.SimpleNamespace(region_name="ap-northeast-2")

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.store[Key])}

    def upload_fileobj(self, fileobj, Bucket, Key, Callback=None):
        data = b""
        while True:
            c = fileobj.read(65536)
            if not c:
                break
            data += c
            if Callback:
                Callback(len(c))
        self.store[Key] = data

    def generate_presigned_url(self, *a, **k):
        return "http://unused-in-relay"


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
    # 강제 릴레이
    transfer_engine.remote_can_reach_s3 = lambda ssh, region: False

    root = tempfile.mkdtemp(prefix="qa-xfer-root-")
    Path(root, "data").mkdir()
    Path(root, "data", "a.txt").write_bytes(b"REMOTE-A" * 1000)

    host_key = paramiko.RSAKey.generate(2048)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    port = sock.getsockname()[1]
    stop = threading.Event()
    threading.Thread(target=_serve, args=(sock, host_key, root, stop), daemon=True).start()

    try:
        ssh = transfer_engine.sftp_engine.connect(
            host="127.0.0.1", port=port, username="qa", password="x", timeout=10
        )
        s3 = FakeS3()
        s3.store["src/hello.bin"] = b"S3-DATA" * 2000

        # 1) S3 → 원격 (keys 모드, 릴레이 스트리밍)
        recv = {"n": 0}
        s, f = transfer_engine.s3_to_remote(
            s3, ssh, "bucket", keys=["src/hello.bin"], remote_dir="/incoming",
            on_bytes=lambda n: recv.__setitem__("n", recv["n"] + n),
        )
        print("S3→원격:", s, f, "| on_bytes:", recv["n"])
        assert (s, f) == (1, 0), (s, f)
        got = Path(root, "incoming", "hello.bin").read_bytes()
        assert got == b"S3-DATA" * 2000, "원격에 기록된 내용 불일치"
        assert recv["n"] == len(got)

        # 2) 원격 → S3 (keys 모드, 릴레이 스트리밍)
        s2, f2 = transfer_engine.remote_to_s3(
            ssh, s3, "bucket", keys=["/data/a.txt"], prefix="backup",
        )
        print("원격→S3:", s2, f2, "| S3 키:", list(s3.store.keys()))
        assert (s2, f2) == (1, 0), (s2, f2)
        assert s3.store["backup/a.txt"] == b"REMOTE-A" * 1000, "S3 업로드 내용 불일치"

        # 3) 직통 curl 커맨드 구성 검증 (가짜 SSH로 exec_command 캡처)
        class FakeSSH:
            def __init__(self):
                self.cmds = []

            def exec_command(self, cmd, timeout=None):
                self.cmds.append(cmd)
                chan = types.SimpleNamespace(
                    recv_exit_status=lambda: 0, exit_status_ready=lambda: True
                )
                stdout = types.SimpleNamespace(channel=chan, read=lambda: b"")
                stderr = types.SimpleNamespace(read=lambda: b"")
                return None, stdout, stderr

        fssh = FakeSSH()
        ok, _ = transfer_engine._direct_download(fssh, "https://s3/x?a=1&b=2", "/dir/sp ace.bin")
        dl_cmd = fssh.cmds[-1]
        print("직통 다운로드 커맨드:", dl_cmd)
        assert ok and "mkdir -p" in dl_cmd and "curl -fsS" in dl_cmd and "-o " in dl_cmd
        assert "'/dir/sp ace.bin'" in dl_cmd, "원격 경로 quoting 오류"
        assert "'https://s3/x?a=1&b=2'" in dl_cmd, "URL quoting 오류(&,= 이스케이프)"

        ok2, _ = transfer_engine._direct_upload(fssh, "https://s3/put?sig=z", "/dir/up load.bin")
        up_cmd = fssh.cmds[-1]
        print("직통 업로드 커맨드:", up_cmd)
        # 공백 포함 경로가 안전하게 quote되는지 확인
        assert ok2 and "curl -fsS" in up_cmd and "-X PUT" in up_cmd and "-T '/dir/up load.bin'" in up_cmd

        ssh.close()
        print("\n✅ S3↔원격 전송(릴레이 + 직통 커맨드 구성) 검증 통과")
    finally:
        stop.set()
        sock.close()


if __name__ == "__main__":
    main()
