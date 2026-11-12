import json
from types import SimpleNamespace

import pytest

from app.stf import normalize_document
from app.stf_browser import STFPortalBrowser


SEARCH_API = "https://jurisprudencia.stf.jus.br/api/search/search"


class FakeRoute:
    def __init__(self, body: object) -> None:
        self.request = SimpleNamespace(url=SEARCH_API, post_data_json=body)
        self.sent_body: dict | None = None
        self.aborted = False

    def continue_(self, post_data: str | None = None) -> None:
        self.sent_body = json.loads(post_data) if post_data else None

    def abort(self, _: str) -> None:
        self.aborted = True


def portal_body() -> dict:
    return {
        "from": 0,
        "size": 10,
        "query": {"function_score": {"query": {"bool": {"filter": [{"term": {"base": "acordaos"}}]}}}},
    }


def browser_for(page: int, page_size: int, filters: list[dict]) -> STFPortalBrowser:
    browser = STFPortalBrowser()
    browser._result_offset = page * page_size
    browser._page_size = page_size
    browser._extra_filters = filters
    return browser


def test_route_sets_page_and_adds_filters_to_portal_request() -> None:
    date_filter = {"range": {"publicacao_data": {"gte": "2024-01-01"}}}
    browser = browser_for(page=2, page_size=100, filters=[date_filter])
    route = FakeRoute(portal_body())

    browser._continue_search_request(route)

    assert route.sent_body["from"] == 200
    assert route.sent_body["size"] == 100
    bool_filters = route.sent_body["query"]["function_score"]["query"]["bool"]["filter"]
    assert bool_filters == [{"term": {"base": "acordaos"}}, date_filter]
    assert browser._search_request_seen


def test_route_blocks_search_when_filters_cannot_be_applied() -> None:
    browser = browser_for(page=0, page_size=100, filters=[{"range": {}}])
    route = FakeRoute({"query": {"match_all": {}}})

    browser._continue_search_request(route)

    assert route.aborted
    assert "filtros" in browser._route_error


def test_route_blocks_search_it_cannot_read() -> None:
    browser = browser_for(page=0, page_size=100, filters=[])
    route = FakeRoute(None)

    browser._continue_search_request(route)

    assert route.aborted


def test_pdf_links_outside_official_hosts_are_rejected() -> None:
    STFPortalBrowser._validate_pdf_url("https://portal.stf.jus.br/doc.pdf", 0)
    with pytest.raises(RuntimeError, match="domínios oficiais"):
        STFPortalBrowser._validate_pdf_url("https://evil.example/doc.pdf", 0)


def test_normalize_document_rejects_missing_identifier() -> None:
    with pytest.raises(ValueError, match="identificador estável"):
        normalize_document({}, "acordaos")


def test_normalize_document_maps_hit() -> None:
    document = normalize_document(
        {
            "base": "acordaos",
            "id": "sjur123",
            "titulo": "RE 123",
            "processo_codigo_completo": "RE 123",
            "publicacao_data": "2024-01-15",
            "inteiro_teor_url": "https://portal.stf.jus.br/documento.pdf",
        },
        "acordaos",
    )

    assert document.document_key == "acordaos:sjur123"
    assert document.process == "RE 123"
    assert document.document_date == "2024-01-15"


def test_browser_rejects_request_delay_below_portal_rate_limit() -> None:
    with pytest.raises(ValueError, match="1 segundo"):
        STFPortalBrowser(request_delay_seconds=0.5)
