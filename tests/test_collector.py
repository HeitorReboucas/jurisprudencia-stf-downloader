import hashlib
import json
from pathlib import Path

from app.collector import Collector
from app.config import Settings
from app.database import Database
from app.stf import STFDocument


def make_document(document_id: str) -> STFDocument:
    return STFDocument(
        document_key=f"acordaos:{document_id}",
        title=f"RE {document_id}",
        process=f"RE {document_id}",
        process_class="RE",
        content_type="acordaos",
        document_date="2024-05-10",
        source_url=f"https://jurisprudencia.stf.jus.br/documento/{document_id}",
        pdf_url=f"https://portal.stf.jus.br/documento/{document_id}.pdf",
    )


def make_job(database: Database, job_id: str = "job-collector") -> None:
    database.create_job(
        job_id,
        {
            "content_types": ["acordaos"],
            "date_from": "2024-01-01",
            "date_to": "2024-12-31",
            "query": "liberdade",
            "process_class": "RE",
            "drive_folder_id": None,
        },
    )


def make_collector(tmp_path) -> tuple[Collector, Database]:
    settings = Settings(_env_file=None, data_dir=tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    return Collector(database, settings), database


class FakeSTF:
    def __init__(self, pages: dict[int, list[STFDocument]]) -> None:
        self.pages = pages
        self.calls: list[int] = []
        self.arguments: list[dict[str, object]] = []

    def search_page(self, *, page: int, **_: object) -> list[STFDocument]:
        self.calls.append(page)
        self.arguments.append(_)
        return self.pages.get(page, [])

    def close(self) -> None:
        pass


class FakeDownloader:
    def __init__(self, content: bytes = b"%PDF-1.7\n%%EOF") -> None:
        self.content = content

    def download(self, _: str, destination) -> tuple[str, int]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.content)
        return hashlib.sha256(self.content).hexdigest(), len(self.content)


def test_collector_deduplicates_hashes_and_finishes_with_correct_counts(tmp_path) -> None:
    collector, database = make_collector(tmp_path)
    make_job(database)
    collector.stf = FakeSTF({0: [make_document("1"), make_document("2")]})
    collector.downloader = FakeDownloader()

    collector.run("job-collector")

    job = database.get_job("job-collector")
    documents = database.list_documents()
    assert job["status"] == "completed"
    assert database.job_counts("job-collector") == {
        "found": 2,
        "downloaded": 1,
        "uploaded": 0,
        "duplicates": 1,
        "errors": 0,
    }
    assert {document["status"] for document in documents} == {"downloaded", "duplicate"}
    downloaded = next(document for document in documents if document["status"] == "downloaded")
    assert downloaded["local_path"]
    assert (tmp_path / "downloads" / "STF").is_dir()
    assert collector.stf.calls == [0, 1]


def test_collector_can_resume_after_stf_failure(tmp_path) -> None:
    collector, database = make_collector(tmp_path)
    make_job(database, "job-resume")

    class FailingOnceSTF:
        def __init__(self) -> None:
            self.should_fail = True

        def search_page(self, **kwargs: object) -> list[STFDocument]:
            if self.should_fail:
                self.should_fail = False
                raise RuntimeError("STF temporariamente indisponível")
            return FakeSTF({0: [make_document("3")]}).search_page(**kwargs)

        def close(self) -> None:
            pass

    collector.stf = FailingOnceSTF()
    collector.downloader = FakeDownloader()

    collector.run("job-resume")
    failed_job = database.get_job("job-resume")
    assert failed_job["status"] == "interrupted"
    assert failed_job["error"] == "STF temporariamente indisponível"

    collector.run("job-resume")
    completed_job = database.get_job("job-resume")
    assert completed_job["status"] == "completed"
    assert database.job_counts("job-resume")["downloaded"] == 1


def test_collector_passes_missing_dates_to_stf_search(tmp_path) -> None:
    collector, database = make_collector(tmp_path)
    database.create_job(
        "job-no-dates",
        {
            "content_types": ["acordaos"],
            "date_from": None,
            "date_to": None,
            "query": "mulheres e direito fundamental",
            "process_class": None,
            "drive_folder_id": None,
        },
    )
    fake_stf = FakeSTF({})
    collector.stf = fake_stf

    collector.run("job-no-dates")

    assert database.get_job("job-no-dates")["status"] == "completed"
    assert fake_stf.arguments[0]["date_from"] is None
    assert fake_stf.arguments[0]["date_to"] is None
    assert fake_stf.arguments[0]["query"] == "mulheres e direito fundamental"


def test_drive_failure_keeps_local_pdf_and_marks_job_error(tmp_path) -> None:
    collector, database = make_collector(tmp_path)
    make_job(database, "job-drive")
    filters_job = database.get_job("job-drive")
    filters = json.loads(filters_job["filters_json"])
    filters["drive_folder_id"] = "drive-root"
    database.update_job("job-drive", status="queued")
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET filters_json = ? WHERE id = ?",
            (json.dumps(filters), "job-drive"),
        )
    collector.stf = FakeSTF({0: [make_document("4")]})
    collector.downloader = FakeDownloader()

    class FailingDrive:
        def is_authorized(self) -> bool:
            return True

        def ensure_archive_folder(self, *_: object) -> str:
            return "year-folder"

        def upload_pdf(self, *_: object) -> str:
            raise RuntimeError("Quota do Drive esgotada")

    collector.drive = FailingDrive()
    collector.run("job-drive")

    job = database.get_job("job-drive")
    document = database.list_documents()[0]
    assert job["status"] == "completed_with_errors"
    assert database.job_counts("job-drive") == {
        "found": 1,
        "downloaded": 1,
        "uploaded": 0,
        "duplicates": 0,
        "errors": 1,
    }
    assert document["status"] == "downloaded"
    assert document["error"] == "Quota do Drive esgotada"
    assert document["local_path"]
    assert Path(document["local_path"]).is_file()

    class RecoveredDrive:
        def is_authorized(self) -> bool:
            return True

        def ensure_archive_folder(self, *_: object) -> str:
            return "year-folder"

        def upload_pdf(self, *_: object) -> str:
            return "drive-file-1"

    collector.drive = RecoveredDrive()
    collector.run("job-drive")

    resumed_job = database.get_job("job-drive")
    uploaded_document = database.list_documents()[0]
    assert resumed_job["status"] == "completed"
    assert database.job_counts("job-drive") == {
        "found": 1,
        "downloaded": 1,
        "uploaded": 1,
        "duplicates": 0,
        "errors": 0,
    }
    assert uploaded_document["status"] == "uploaded"
    assert uploaded_document["drive_file_id"] == "drive-file-1"
    assert Path(uploaded_document["local_path"]).is_file()

def test_uploaded_document_goes_to_each_new_drive_folder(tmp_path) -> None:
    collector, database = make_collector(tmp_path)
    collector.downloader = FakeDownloader()

    class RecordingDrive:
        def __init__(self) -> None:
            self.uploads: list[str] = []

        def is_authorized(self) -> bool:
            return True

        def ensure_archive_folder(self, root_folder_id: str, *_: object) -> str:
            return root_folder_id

        def upload_pdf(self, _: Path, folder_id: str, __: str) -> str:
            self.uploads.append(folder_id)
            return f"file-in-{folder_id}"

    drive = RecordingDrive()
    collector.drive = drive
    for job_id, folder in (("job-a", "folder-a"), ("job-b", "folder-b"), ("job-local", None)):
        database.create_job(
            job_id,
            {"content_types": ["acordaos"], "query": "liberdade", "drive_folder_id": folder},
        )
        collector.stf = FakeSTF({0: [make_document("5")]})
        collector.run(job_id)

    assert drive.uploads == ["folder-a", "folder-b"]
    assert database.job_counts("job-b")["uploaded"] == 1
    assert database.job_counts("job-local")["uploaded"] == 0
    assert database.job_counts("job-local")["downloaded"] == 1
