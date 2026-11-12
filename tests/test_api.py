from fastapi.testclient import TestClient

import app.main as main
from app.database import Database


class IdleCollector:
    def __init__(self) -> None:
        self.run_calls: list[str] = []

    def run(self, _: str) -> None:
        self.run_calls.append(_)


def test_api_creates_and_reads_a_job(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "state.sqlite3")
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main, "collector", IdleCollector())

    with TestClient(main.app) as client:
        health = client.get("/api/health")
        types = client.get("/api/content-types")
        created = client.post(
            "/api/jobs",
            json={
                "content_types": ["acordaos"],
                "date_from": "2024-01-01",
                "date_to": "2024-12-31",
                "query": "liberdade",
            },
        )

        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert {item["id"] for item in types.json()} == {
            "acordaos",
            "decisoes_monocraticas",
        }
        assert created.status_code == 202
        job_id = created.json()["id"]
        assert created.json()["status"] == "queued"
        assert client.get(f"/api/jobs/{job_id}").json()["query"] == "liberdade"
        assert len(client.get(f"/api/jobs/{job_id}/events").json()) == 1


def test_api_rejects_invalid_date_range(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "state.sqlite3")
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main, "collector", IdleCollector())

    with TestClient(main.app) as client:
        response = client.post(
            "/api/jobs",
            json={
                "content_types": ["acordaos"],
                "date_from": "2024-12-31",
                "date_to": "2024-01-01",
            },
        )

    assert response.status_code == 422


def test_api_accepts_keyword_search_without_dates(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "state.sqlite3")
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main, "collector", IdleCollector())

    with TestClient(main.app) as client:
        response = client.post(
            "/api/jobs",
            json={
                "content_types": ["acordaos"],
                "query": "mulheres e direito fundamental",
            },
        )

    assert response.status_code == 202
    assert response.json()["date_from"] is None
    assert response.json()["date_to"] is None
    assert response.json()["query"] == "mulheres e direito fundamental"


def test_api_requires_keywords_when_both_dates_are_omitted(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "state.sqlite3")
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main, "collector", IdleCollector())

    with TestClient(main.app) as client:
        response = client.post("/api/jobs", json={"content_types": ["acordaos"]})

    assert response.status_code == 422
    assert "palavras-chave" in response.text


def test_api_serves_interface_and_openapi_contract(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "state.sqlite3")
    monkeypatch.setattr(main, "database", database)

    with TestClient(main.app) as client:
        page = client.get("/")
        schema = client.get("/openapi.json").json()

    assert page.status_code == 200
    assert "Jurisprudência STF" in page.text
    assert "/api/jobs/{job_id}/resume" in schema["paths"]
    assert "/api/documents/{document_id}/upload" in schema["paths"]


def test_api_resumes_interrupted_job(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    database.create_job(
        "resume-me",
        {
            "content_types": ["acordaos"],
            "date_from": "2024-01-01",
            "date_to": "2024-12-31",
            "query": None,
            "process_class": None,
            "drive_folder_id": None,
        },
    )
    database.update_job("resume-me", status="interrupted")
    collector = IdleCollector()
    monkeypatch.setattr(main, "database", database)
    monkeypatch.setattr(main, "collector", collector)

    with TestClient(main.app) as client:
        response = client.post("/api/jobs/resume-me/resume")
        missing = client.post("/api/jobs/missing/resume")

    assert response.status_code == 202
    assert response.json()["id"] == "resume-me"
    assert collector.run_calls == ["resume-me"]
    assert missing.status_code == 404


def test_api_lists_documents_and_returns_not_found_for_unknown_upload(
    tmp_path, monkeypatch
) -> None:
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    database.insert_document(
        {
            "document_key": "acordaos:sjur9",
            "title": "RE 9",
            "process": "RE 9",
            "process_class": "RE",
            "content_type": "acordaos",
            "document_date": "2024-01-01",
            "source_url": "https://jurisprudencia.stf.jus.br/",
            "pdf_url": None,
            "status": "pending",
        }
    )
    monkeypatch.setattr(main, "database", database)

    with TestClient(main.app) as client:
        documents = client.get("/api/documents?content_type=acordaos&limit=10")
        unknown = client.post(
            "/api/documents/999/upload", json={"drive_folder_id": "drive-root"}
        )

    assert documents.status_code == 200
    assert len(documents.json()) == 1
    assert documents.json()[0]["document_key"] == "acordaos:sjur9"
    assert unknown.status_code == 404