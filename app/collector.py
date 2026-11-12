import json
import threading
from datetime import date
from pathlib import Path
from typing import Any

from app.config import Settings
from app.database import Database
from app.downloader import PDFDownloader
from app.drive import DriveIntegrationError, GoogleDriveClient
from app.organizer import pdf_path
from app.stf import STFDocument
from app.stf_browser import STFPortalBrowser


PAGE_SIZE = 100
COLLECTION_LOCK = threading.Semaphore(1)


class Collector:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self.stf = STFPortalBrowser(
            timeout_seconds=settings.stf_timeout_seconds,
            request_delay_seconds=settings.stf_request_delay_seconds,
            browser_channel=settings.stf_browser_channel,
        )
        self.downloader = PDFDownloader(
            timeout_seconds=settings.download_timeout_seconds,
            max_bytes=settings.download_max_bytes,
            max_attempts=settings.stf_max_attempts,
        )
        self.drive = GoogleDriveClient(settings)

    def run(self, job_id: str) -> None:
        with COLLECTION_LOCK:
            try:
                self._run_locked(job_id)
            finally:
                self.stf.close()

    def _run_locked(self, job_id: str) -> None:
        job = self.database.get_job(job_id)
        if job is None:
            return

        filters = json.loads(job["filters_json"])
        checkpoint = json.loads(job["checkpoint_json"] or "{}")
        content_types = filters["content_types"]
        start_content_index = int(checkpoint.get("content_type_index", 0))
        start_page = int(checkpoint.get("page", 0))
        counts = self.database.job_counts(job_id)
        self.database.update_job(job_id, status="running", error=None)
        self.database.add_event(job_id, "info", "Coleta iniciada ou retomada.")

        try:
            for content_index in range(start_content_index, len(content_types)):
                content_type = content_types[content_index]
                page = start_page if content_index == start_content_index else 0
                while True:
                    documents = self.stf.search_page(
                        query=filters.get("query"),
                        content_type=content_type,
                        date_from=(
                            date.fromisoformat(filters["date_from"])
                            if filters.get("date_from")
                            else None
                        ),
                        date_to=(
                            date.fromisoformat(filters["date_to"])
                            if filters.get("date_to")
                            else None
                        ),
                        process_class=filters.get("process_class"),
                        page=page,
                        page_size=PAGE_SIZE,
                    )
                    if not documents:
                        break

                    for document in documents:
                        self.database.update_job(job_id, current_item=document.title)
                        self._process_document(
                            job_id,
                            document,
                            filters.get("drive_folder_id"),
                        )
                        counts = self.database.job_counts(job_id)
                        self.database.update_job(job_id, **counts)

                    page += 1
                    self.database.update_job(
                        job_id,
                        checkpoint_json=json.dumps(
                            {"content_type_index": content_index, "page": page}
                        ),
                        **counts,
                    )

                start_page = 0
                self.database.update_job(
                    job_id,
                    checkpoint_json=json.dumps(
                        {"content_type_index": content_index + 1, "page": 0}
                    ),
                )

            status = "completed_with_errors" if counts["errors"] else "completed"
            self.database.update_job(
                job_id,
                status=status,
                current_item=None,
                checkpoint_json="{}",
                **counts,
            )
            self.database.add_event(job_id, "info", "Coleta finalizada.")
        except Exception as error:
            self.database.update_job(
                job_id,
                status="interrupted",
                error=str(error),
                current_item=None,
                **counts,
            )
            self.database.add_event(job_id, "error", f"Execução interrompida: {error}")

    def _process_document(
        self,
        job_id: str,
        document: STFDocument,
        drive_folder_id: str | None,
    ) -> None:
        document_data = {
            "document_key": document.document_key,
            "title": document.title,
            "process": document.process,
            "process_class": document.process_class,
            "content_type": document.content_type,
            "document_date": document.document_date,
            "source_url": document.source_url,
            "pdf_url": document.pdf_url,
            "status": "pending",
        }
        record = self.database.insert_document(document_data)
        self.database.link_job_document(job_id, record["id"])
        if record["status"] == "duplicate":
            self.database.update_job_document_status(job_id, record["id"], "duplicate")
            return

        # An "uploaded" document still goes on: this job may target another Drive folder.
        local_path = Path(record["local_path"]) if record.get("local_path") else None
        if record["status"] in {"downloaded", "uploaded"} and local_path and local_path.is_file():
            self.database.update_job_document_status(job_id, record["id"], "downloaded")
        else:
            local_path = pdf_path(self.settings.downloads_dir, document)
            if not document.pdf_url:
                self._mark_document_error(
                    job_id,
                    record,
                    "Documento sem URL de inteiro teor disponível no portal.",
                )
                return
            try:
                self.database.update_document(
                    record["id"], status="downloading", attempts=record["attempts"] + 1
                )
                digest, _ = self.downloader.download(document.pdf_url, local_path)
                duplicate = self.database.find_document_by_hash(digest)
                if duplicate and duplicate["id"] != record["id"]:
                    local_path.unlink(missing_ok=True)
                    self.database.update_document(
                        record["id"], status="duplicate", hash_sha256=digest, local_path=None
                    )
                    self.database.update_job_document_status(job_id, record["id"], "duplicate")
                    return

                self.database.update_document(
                    record["id"],
                    status="downloaded",
                    local_path=str(local_path),
                    hash_sha256=digest,
                    error=None,
                )
                self.database.update_job_document_status(job_id, record["id"], "downloaded")
            except Exception as error:
                self._mark_document_error(job_id, record, str(error))
                return

        if not drive_folder_id:
            return
        if not self.drive.is_authorized():
            self.database.update_document(record["id"], error="Google Drive não autorizado.")
            self.database.update_job_document_status(job_id, record["id"], "error_upload")
            self.database.add_event(
                job_id,
                "warning",
                f"PDF preservado localmente; Drive não autorizado: {document.title}",
            )
            return

        try:
            archive_folder_id = self.drive.ensure_archive_folder(
                drive_folder_id, document.content_type, document.document_date
            )
            drive_file_id = self.drive.upload_pdf(
                local_path,
                archive_folder_id,
                document.document_key,
            )
            self.database.update_document(
                record["id"], status="uploaded", drive_file_id=drive_file_id, error=None
            )
            self.database.update_job_document_status(job_id, record["id"], "uploaded")
        except Exception as error:
            self.database.update_document(record["id"], error=str(error))
            self.database.update_job_document_status(job_id, record["id"], "error_upload")
            self.database.add_event(
                job_id,
                "error",
                f"Upload falhou; PDF preservado localmente ({document.title}): {error}",
            )

    def _mark_document_error(
        self, job_id: str, record: dict[str, Any], message: str
    ) -> None:
        self.database.update_document(
            record["id"], status="error", error=message[:2000]
        )
        self.database.update_job_document_status(job_id, record["id"], "error_download")

    def upload_document(self, document_id: int, folder_id: str) -> dict[str, Any]:
        record = self.database.get_document(document_id)
        if record is None:
            raise LookupError("Documento não encontrado")
        if not record["local_path"] or not Path(record["local_path"]).is_file():
            raise FileNotFoundError("PDF local não encontrado; execute a coleta novamente")
        if not self.drive.is_authorized():
            raise DriveIntegrationError("Google Drive não autorizado")

        archive_folder_id = self.drive.ensure_archive_folder(
            folder_id, record["content_type"], record["document_date"]
        )
        drive_file_id = self.drive.upload_pdf(
            Path(record["local_path"]), archive_folder_id, record["document_key"]
        )
        self.database.update_document(
            document_id, status="uploaded", drive_file_id=drive_file_id, error=None
        )
        updated_record = self.database.get_document(document_id)
        if updated_record is None:
            raise LookupError("Documento não encontrado após upload")
        return updated_record


def serialize_job(row: dict[str, Any]) -> dict[str, Any]:
    filters = json.loads(row["filters_json"])
    return {
        "id": row["id"],
        "status": row["status"],
        **filters,
        "found": row["found"],
        "downloaded": row["downloaded"],
        "uploaded": row["uploaded"],
        "duplicates": row["duplicates"],
        "errors": row["errors"],
        "current_item": row["current_item"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }