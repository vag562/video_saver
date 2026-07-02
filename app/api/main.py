from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.db.models import DownloadJob, JobStatus
from app.db.session import SyncSessionLocal
from app.services.storage import safe_unlink

app = FastAPI(title="Video Saver API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/downloads/{token}")
def download_file(token: str) -> FileResponse:
    with SyncSessionLocal() as session:
        job = session.query(DownloadJob).filter_by(download_token=token, status=JobStatus.ready).one_or_none()
        if not job or not job.file_path:
            raise HTTPException(status_code=404, detail="Link not found or expired")
        if job.expires_at and job.expires_at <= datetime.now(UTC):
            safe_unlink(job.file_path)
            job.status = JobStatus.expired
            job.download_token = None
            session.commit()
            raise HTTPException(status_code=410, detail="Link expired")
        path = Path(job.file_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(path, filename=path.name)
