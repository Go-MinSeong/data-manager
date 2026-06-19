"""QA: 작업 이력 영속화 — 완료 잡이 디스크에 저장되고 재시작 시 로드되는지 검증."""
import tempfile
from pathlib import Path

from s3manager.core import jobs as jobs_module
from s3manager.core.jobs import JobManager, JobState


def main():
    hist = Path(tempfile.mkdtemp(prefix="qa-persist-")) / "jobs.json"

    jm = JobManager()
    jm._history_path = hist

    # 완료 잡 1건을 직접 구성해 영속화
    job = JobState(job_id="job-123", kind="remote-download")
    job.status = "done"
    job.total_files = 5
    job.completed_files = 5
    jm._jobs[job.job_id] = job
    jm._persist()

    assert hist.exists(), "이력 파일이 생성되지 않음"

    # 재시작 시뮬레이션 — 같은 경로로 새 매니저 생성 시 로드돼야 함
    jm2 = JobManager()
    jm2._history_path = hist
    jm2._jobs.clear()
    jm2._load_persisted()

    loaded = jm2.get_job("job-123")
    assert loaded is not None, "이력에서 잡을 복원하지 못함"
    assert loaded.status == "done" and loaded.kind == "remote-download"
    assert loaded.completed_files == 5
    print("복원된 잡:", loaded.job_id, loaded.kind, loaded.status, loaded.completed_files)
    print("\n✅ 작업 이력 영속화 검증 통과")


if __name__ == "__main__":
    main()
