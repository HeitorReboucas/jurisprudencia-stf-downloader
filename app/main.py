import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app.collector import Collector, serialize_job
from app.config import get_settings
from app.database import Database
from app.drive import DriveIntegrationError
from app.models import CollectionRequest, DriveAuthResponse, EventResponse, JobResponse


settings = get_settings()
database = Database(settings.database_path)
collector = Collector(database, settings)
static_dir = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    for job_id in database.interrupt_running_jobs():
        database.add_event(
            job_id,
            "warning",
            "Execução anterior interrompida. Use a operação de retomada para continuar.",
        )
    yield


app = FastAPI(
    title=settings.app_name,
    description="Coleta local, retomável e auditável de documentos públicos do STF.",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


class UploadRequest(BaseModel):
    drive_folder_id: str = Field(min_length=1, max_length=300)


class DownloadsFolderRequest(BaseModel):
    # Empty path = back to the default folder inside DATA_DIR.
    path: str = Field(default="", max_length=1000)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    # no-cache: browsers must revalidate, or they keep showing an outdated interface after updates.
    return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/health", tags=["Sistema"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/content-types", tags=["Coleta"])
def content_types() -> list[dict[str, str]]:
    return [
        {"id": "acordaos", "label": "Acórdãos"},
        {"id": "decisoes_monocraticas", "label": "Decisões monocráticas"},
    ]


@app.post("/api/jobs", response_model=JobResponse, status_code=202, tags=["Coleta"])
def create_job(
    request: CollectionRequest, background_tasks: BackgroundTasks
) -> dict[str, object]:
    job_id = str(uuid4())
    database.create_job(job_id, request.model_dump(mode="json"))
    database.add_event(job_id, "info", "Coleta colocada na fila.")
    background_tasks.add_task(collector.run, job_id)
    row = database.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Não foi possível criar a coleta")
    return serialize_job(row)


@app.get("/api/jobs", response_model=list[JobResponse], tags=["Coleta"])
def list_jobs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, object]]:
    return [serialize_job(row) for row in database.list_jobs(limit)]


@app.get("/api/jobs/{job_id}", response_model=JobResponse, tags=["Coleta"])
def get_job(job_id: str) -> dict[str, object]:
    row = database.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Coleta não encontrada")
    return serialize_job(row)


@app.get("/api/jobs/{job_id}/events", response_model=list[EventResponse], tags=["Coleta"])
def list_job_events(
    job_id: str, limit: int = Query(default=100, ge=1, le=500)
) -> list[dict[str, object]]:
    if database.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Coleta não encontrada")
    return database.list_events(job_id, limit)


@app.post("/api/jobs/{job_id}/resume", response_model=JobResponse, status_code=202, tags=["Coleta"])
def resume_job(job_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
    row = database.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Coleta não encontrada")
    if row["status"] not in {"interrupted", "completed_with_errors"}:
        raise HTTPException(
            status_code=409,
            detail="Somente coletas interrompidas ou com erro podem ser retomadas",
        )
    database.update_job(job_id, status="queued", error=None)
    database.add_event(job_id, "info", "Retomada solicitada.")
    background_tasks.add_task(collector.run, job_id)
    updated_row = database.get_job(job_id)
    if updated_row is None:
        raise HTTPException(status_code=404, detail="Coleta não encontrada")
    return serialize_job(updated_row)


@app.get("/api/documents", tags=["Documentos"])
def list_documents(
    content_type: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, object]]:
    return database.list_documents(
        content_type=content_type,
        status=status,
        limit=limit,
        offset=offset,
    )


@app.post("/api/documents/{document_id}/upload", tags=["Documentos"])
def upload_document(document_id: int, request: UploadRequest) -> dict[str, object]:
    try:
        return collector.upload_document(document_id, request.drive_folder_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (FileNotFoundError, DriveIntegrationError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Falha no envio ao Drive: {error}") from error


def downloads_folder_info() -> dict[str, object]:
    return {
        "path": str(collector.downloads_dir().resolve()),
        "is_default": database.get_setting("downloads_dir") is None,
    }


@app.get("/api/downloads-folder", tags=["Documentos"])
def get_downloads_folder() -> dict[str, object]:
    return downloads_folder_info()


@app.put("/api/downloads-folder", tags=["Documentos"])
def set_downloads_folder(request: DownloadsFolderRequest) -> dict[str, object]:
    raw_path = request.path.strip()
    if not raw_path:
        database.set_setting("downloads_dir", None)
        return downloads_folder_info()

    folder = Path(raw_path).expanduser()
    if not folder.is_absolute():
        raise HTTPException(
            status_code=400,
            detail="Informe o caminho completo da pasta, por exemplo C:\\Users\\voce\\Documents\\STF.",
        )
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".coletor-stf-teste-de-escrita"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as error:
        raise HTTPException(
            status_code=400, detail=f"Não foi possível salvar arquivos nessa pasta: {error}"
        ) from error
    database.set_setting("downloads_dir", str(folder.resolve()))
    return downloads_folder_info()


@app.post("/api/downloads-folder/open", status_code=204, tags=["Documentos"])
def open_downloads_folder() -> Response:
    # The server runs on the user's own computer, so the folder opens there.
    folder = collector.downloads_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Não foi possível abrir a pasta: {error}") from error
    return Response(status_code=204)


@app.get("/api/drive/status", tags=["Google Drive"])
def drive_status() -> dict[str, bool]:
    return {
        "configured": collector.drive.is_configured(),
        "authorized": collector.drive.is_authorized(),
    }


@app.get("/api/drive/auth/url", response_model=DriveAuthResponse, tags=["Google Drive"])
def drive_auth_url() -> dict[str, str]:
    try:
        return {"authorization_url": collector.drive.create_authorization_url()}
    except DriveIntegrationError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/drive/oauth/callback", response_class=HTMLResponse, include_in_schema=False)
def drive_oauth_callback(code: str, state: str) -> HTMLResponse:
    try:
        collector.drive.complete_authorization(code, state)
    except DriveIntegrationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return HTMLResponse(
        "<main><h1>Google Drive conectado</h1>"
        "<p>A autorização foi salva localmente. Você pode fechar esta janela.</p></main>"
    )


@app.get("/api/drive/folders", tags=["Google Drive"])
def list_drive_folders() -> list[dict[str, str]]:
    try:
        return collector.drive.list_folders()
    except DriveIntegrationError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Falha ao consultar Google Drive: {error}") from error