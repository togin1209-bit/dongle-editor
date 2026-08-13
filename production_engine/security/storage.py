"""
security/storage.py
--------------------
Job(작업) 단위 저장공간 격리 관리.

디렉토리 구조:
  {root}/jobs/{job_id}/
      original/     # 고객이 업로드한 원본 (읽기 전용, 절대 덮어쓰지 않음)
      working/      # 편집(리사이즈/크롭/미리보기) 중간 산출물
      output/       # 최종 Production 파일 (CMYK PDF/X 등, 인쇄소 전달용)
      job.lock      # 동시 수정 방지용 락 파일

설계 원칙:
- job_id 는 예측 불가능한 UUID (순차 ID 금지) → 타 고객 작업 추측 접근 방지.
- original/ 은 생성 시 1회만 쓰고 이후 read-only 로 취급한다 (편집은 항상 working/ 에서).
- 동시 작업 보호는 filelock 기반 - Windows/Linux 단일 서버 MVP 구현이다.
  ** 다중 서버(수평 확장) 배포 시에는 Redis 분산 락 등으로 교체가 필요하다. (한계 사항 참고) **
"""

from __future__ import annotations

import contextlib
import os
import shutil
import time
import uuid
from dataclasses import dataclass

# filelock is preferred, but DONGLE Studio can still start if pip installation
# was interrupted/offline. This fallback is suitable for the local Windows MVP.
try:
    from filelock import FileLock, Timeout
except ImportError:
    class Timeout(Exception):
        pass

    class FileLock:
        def __init__(self, lock_file, timeout=-1):
            self.lock_file = lock_file
            self.timeout = timeout
            self._fd = None

        def acquire(self, timeout=None):
            import time as _time
            limit = self.timeout if timeout is None else timeout
            start = _time.time()
            while True:
                try:
                    self._fd = os.open(
                        self.lock_file,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY
                    )
                    os.write(self._fd, str(os.getpid()).encode("ascii"))
                    return self
                except FileExistsError:
                    if limit is not None and limit >= 0 and (_time.time() - start) >= limit:
                        raise Timeout(self.lock_file)
                    _time.sleep(0.1)

        def release(self):
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None
            try:
                os.remove(self.lock_file)
            except FileNotFoundError:
                pass

        def __enter__(self):
            return self.acquire()

        def __exit__(self, exc_type, exc, tb):
            self.release()


class StorageError(Exception):
    pass


class JobLockTimeout(StorageError):
    pass


@dataclass
class JobPaths:
    root: str
    original_dir: str
    working_dir: str
    output_dir: str
    lock_file: str


def new_job_id() -> str:
    return str(uuid.uuid4())


class JobStorage:
    def __init__(self, storage_root: str):
        self.storage_root = storage_root
        os.makedirs(self.storage_root, exist_ok=True)

    def _job_root(self, job_id: str) -> str:
        # job_id 는 UUID 형식만 허용 (path traversal 방어: "../../etc" 같은 값이 들어오지 못하게)
        if not _is_valid_uuid(job_id):
            raise StorageError(f"유효하지 않은 job_id: {job_id!r}")
        return os.path.join(self.storage_root, "jobs", job_id)

    def create_job(self) -> JobPaths:
        job_id = new_job_id()
        root = self._job_root(job_id)
        original_dir = os.path.join(root, "original")
        working_dir = os.path.join(root, "working")
        output_dir = os.path.join(root, "output")
        for d in (original_dir, working_dir, output_dir):
            os.makedirs(d, exist_ok=True)
        return JobPaths(
            root=root,
            original_dir=original_dir,
            working_dir=working_dir,
            output_dir=output_dir,
            lock_file=os.path.join(root, "job.lock"),
        )

    def get_paths(self, job_id: str) -> JobPaths:
        root = self._job_root(job_id)
        if not os.path.isdir(root):
            raise StorageError(f"존재하지 않는 job: {job_id}")
        return JobPaths(
            root=root,
            original_dir=os.path.join(root, "original"),
            working_dir=os.path.join(root, "working"),
            output_dir=os.path.join(root, "output"),
            lock_file=os.path.join(root, "job.lock"),
        )

    def save_original(self, job_id: str, filename: str, data_stream) -> str:
        """
        원본 파일 저장. original/ 디렉토리에 파일이 이미 있으면 예외를 던진다
        (원본은 절대 덮어쓰지 않는다 - '고객 원본 파일 보존' 원칙).
        """
        paths = self.get_paths(job_id)
        existing = os.listdir(paths.original_dir)
        if existing:
            raise StorageError(
                f"job {job_id} 에는 이미 원본 파일이 존재합니다 ({existing}). "
                "원본은 덮어쓸 수 없습니다. 새 job을 생성하세요."
            )
        # 파일명은 신뢰하지 않고 안전한 이름으로 재생성 (확장자만 원본 참고)
        safe_ext = _safe_extension(filename)
        dest_path = os.path.join(paths.original_dir, f"source{safe_ext}")
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(data_stream, f)
        # 원본은 이후 실수로라도 수정되지 않도록 읽기 전용으로 권한을 낮춘다.
        os.chmod(dest_path, 0o444)
        return dest_path

    @contextlib.contextmanager
    def job_lock(self, job_id: str, timeout_sec: float = 10.0):
        """Windows/Linux 공통 job 락. filelock 기반."""
        paths = self.get_paths(job_id)
        lock = FileLock(paths.lock_file + ".filelock", timeout=timeout_sec)
        try:
            with lock:
                yield
        except Timeout as exc:
            raise JobLockTimeout(
                f"job {job_id} 락 획득 실패 (다른 요청이 처리 중입니다)"
            ) from exc

    def cleanup_orphan_jobs(self, older_than_sec: float, keep_statuses: tuple[str, ...] = ("done",)):
        """
        실패/중단된 job 의 임시 파일을 정리한다.
        실제 운영에서는 job 상태를 DB에서 조회해 판단해야 하며,
        여기서는 파일 mtime 기반의 단순 참고 구현만 제공한다.
        """
        jobs_dir = os.path.join(self.storage_root, "jobs")
        if not os.path.isdir(jobs_dir):
            return []
        removed = []
        now = time.time()
        for job_id in os.listdir(jobs_dir):
            job_path = os.path.join(jobs_dir, job_id)
            if not os.path.isdir(job_path):
                continue
            mtime = os.path.getmtime(job_path)
            if now - mtime > older_than_sec:
                # 실제 구현에서는 여기서 status 를 확인해야 함 (DB 조회) - MVP 단순화
                shutil.rmtree(job_path, ignore_errors=True)
                removed.append(job_id)
        return removed


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _safe_extension(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    allowed = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    return ext if ext in allowed else ".bin"
