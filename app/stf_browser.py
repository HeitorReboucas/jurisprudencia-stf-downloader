from __future__ import annotations

import json
import platform
import re
import time
from datetime import date
from typing import Any
from urllib.parse import urlencode, urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    Route,
    sync_playwright,
)

from app.stf import (
    CONTENT_BASES,
    RESULT_BASES,
    STFDocument,
    STFTemporaryUnavailable,
    normalize_document,
)


STF_SEARCH_PAGE = "https://jurisprudencia.stf.jus.br/pages/search"
STF_SEARCH_API_FRAGMENT = "/api/search/search"
STF_SEARCH_API_PATTERN = re.compile(
    r"^https://jurisprudencia\.stf\.jus\.br/api/search/search/?(?:\?.*)?$"
)
ALLOWED_PDF_HOSTS = {"portal.stf.jus.br", "www.stf.jus.br"}


class STFResponseValidationError(RuntimeError):
    pass


class STFPortalBrowser:
    def __init__(
        self,
        *,
        timeout_seconds: float = 60,
        request_delay_seconds: float = 1.0,
        browser_channel: str | None = None,
    ) -> None:
        if request_delay_seconds < 1.0:
            raise ValueError("O intervalo mínimo entre pesquisas do STF é 1 segundo")
        self.timeout_ms = int(timeout_seconds * 1000)
        self.request_delay_seconds = request_delay_seconds
        self.browser_channel = browser_channel or (
            "msedge" if platform.system() == "Windows" else None
        )
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._extra_filters: list[dict[str, Any]] = []
        self._result_offset = 0
        self._page_size = 100
        self._route_error: str | None = None
        self._request_failures: list[str] = []
        self._search_request_seen = False

    def search_page(
        self,
        *,
        query: str | None,
        content_type: str,
        date_from: date | None,
        date_to: date | None,
        process_class: str | None,
        page: int,
        page_size: int = 100,
    ) -> list[STFDocument]:
        base = CONTENT_BASES.get(content_type)
        if base is None:
            raise ValueError(f"Tipo de conteúdo não suportado: {content_type}")
        if not query or not query.strip():
            raise ValueError("A pesquisa pelo portal exige palavras-chave")
        if page < 0 or page_size < 1:
            raise ValueError("A página e o tamanho da página devem ser válidos")

        self._ensure_browser()
        assert self._page is not None
        self._extra_filters = self._build_extra_filters(
            date_from, date_to, process_class
        )
        # Set on the outgoing request, so the form fallback cannot lose the page.
        self._result_offset = page * page_size
        self._page_size = page_size
        self._route_error = None
        self._request_failures.clear()
        self._search_request_seen = False
        search_url = self._build_search_url(
            base=base,
            query=query.strip(),
            page=page,
            page_size=page_size,
        )
        time.sleep(self.request_delay_seconds)

        try:
            response = self._open_search_and_capture(query, search_url)
            self._validate_api_url(response.url)
            if response.status == 202 and not response.body():
                raise STFTemporaryUnavailable(
                    "O portal STF retornou HTTP 202 com resposta vazia; "
                    "aguarde antes de iniciar outra coleta."
                )
            if not response.ok:
                raise RuntimeError(
                    f"A pesquisa oficial do STF respondeu HTTP {response.status}."
                )

            payload = response.json()
            hits = self._validate_search_response(payload)
            documents = []
            for index, hit in enumerate(hits):
                source = hit.get("_source")
                try:
                    document = normalize_document(source, content_type)
                except (TypeError, ValueError) as error:
                    raise STFResponseValidationError(
                        f"Resultado {index + 1} do STF está sem metadados válidos: {error}"
                    ) from error
                if document.content_type != content_type:
                    raise STFResponseValidationError(
                        f"Resultado {index + 1} pertence a uma base inesperada."
                    )
                if source.get("base") not in RESULT_BASES[content_type]:
                    raise STFResponseValidationError(
                        f"Resultado {index + 1} veio de uma base inesperada do STF."
                    )
                self._validate_pdf_url(document.pdf_url, index)
                documents.append(document)
            return documents
        except (STFTemporaryUnavailable, STFResponseValidationError):
            raise
        except PlaywrightTimeoutError as error:
            if self._route_error:
                raise STFResponseValidationError(self._route_error) from error
            if self._request_failures:
                failures = "; ".join(self._request_failures[-3:])
                raise RuntimeError(
                    f"A chamada do navegador ao serviço de pesquisa do STF falhou: {failures}"
                ) from error
            if not self._search_request_seen:
                raise RuntimeError(
                    "A página do STF abriu, mas não iniciou a chamada de pesquisa. "
                    "O portal pode ter alterado seu funcionamento; abra a busca no site "
                    "e tente novamente mais tarde."
                ) from error
            if self._page and not self._page.url.startswith(STF_SEARCH_PAGE):
                raise RuntimeError(
                    "O navegador não conseguiu carregar a página de pesquisa do STF. "
                    "Confira sua conexão, proxy ou firewall."
                ) from error
            raise RuntimeError(
                f"A página do STF abriu, mas não recebemos a resposta da pesquisa "
                f"em {self.timeout_ms // 1000} segundos. Confira proxy/firewall ou "
                "tente novamente mais tarde."
            ) from error
        except PlaywrightError as error:
            raise RuntimeError(
                f"Não foi possível pesquisar no portal oficial do STF: {error}"
            ) from error
        except (ValueError, json.JSONDecodeError) as error:
            raise STFResponseValidationError(
                "O portal STF não devolveu um JSON válido para a pesquisa."
            ) from error

    def close(self) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _ensure_browser(self) -> None:
        if self._page:
            return
        self._playwright = sync_playwright().start()
        try:
            launch_options: dict[str, Any] = {"headless": True}
            if self.browser_channel:
                launch_options["channel"] = self.browser_channel
            self._browser = self._playwright.chromium.launch(**launch_options)
        except PlaywrightError as error:
            self._playwright.stop()
            self._playwright = None
            if self.browser_channel == "msedge":
                message = (
                    "O Microsoft Edge não foi encontrado para a pesquisa automatizada. "
                    "Instale o Edge ou configure STF_BROWSER_CHANNEL."
                )
            else:
                message = (
                    "O Chromium do Playwright não está instalado. "
                    "Execute `python -m playwright install chromium`."
                )
            raise RuntimeError(message) from error

        assert self._browser is not None
        self._context = self._browser.new_context(accept_downloads=True)
        self._context.route(STF_SEARCH_API_PATTERN, self._continue_search_request)
        self._page = self._context.new_page()
        self._page.on("request", self._record_search_request)
        self._page.on("requestfailed", self._record_request_failure)

    def _open_search_and_capture(self, query: str, search_url: str) -> Any:
        assert self._page is not None
        matches_search_api = lambda response: bool(
            STF_SEARCH_API_PATTERN.fullmatch(response.url)
        )
        direct_navigation_error: Exception | None = None

        try:
            with self._page.expect_response(
                matches_search_api,
                timeout=min(self.timeout_ms, 12_000),
            ) as response_info:
                self._page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout_ms,
                )
            return response_info.value
        except PlaywrightTimeoutError as error:
            direct_navigation_error = error

        if self._route_error:
            raise STFResponseValidationError(self._route_error) from direct_navigation_error
        if self._request_failures:
            failures = "; ".join(self._request_failures[-3:])
            raise RuntimeError(
                f"A chamada iniciada pelo portal STF falhou: {failures}"
            ) from direct_navigation_error
        if self._search_request_seen:
            raise STFTemporaryUnavailable(
                "O portal iniciou a pesquisa pela URL, mas não devolveu a resposta. "
                "Aguarde e tente novamente mais tarde."
            ) from direct_navigation_error

        try:
            self._page.goto(
                STF_SEARCH_PAGE,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
            search_field = self._page.locator(
                'input[placeholder="Pesquisar palavras-chave"]'
            ).first
            search_field.wait_for(state="visible", timeout=self.timeout_ms)
            search_field.fill(query)
            with self._page.expect_response(
                matches_search_api,
                timeout=self.timeout_ms,
            ) as response_info:
                search_field.press("Enter")
            return response_info.value
        except PlaywrightTimeoutError as error:
            if self._route_error:
                raise STFResponseValidationError(self._route_error) from error
            if self._request_failures:
                failures = "; ".join(self._request_failures[-3:])
                raise RuntimeError(
                    f"A busca pelo formulário do STF falhou: {failures}"
                ) from error
            if self._search_request_seen:
                raise STFTemporaryUnavailable(
                    "O formulário iniciou a pesquisa, mas o STF não devolveu "
                    "os resultados no tempo esperado. Aguarde antes de tentar novamente."
                ) from error
            raise RuntimeError(
                "O STF abriu, mas nem a URL de pesquisa nem o formulário iniciaram "
                "uma chamada ao serviço de resultados. O portal pode ter mudado "
                "ou estar indisponível."
            ) from error

    def _record_search_request(self, request: Any) -> None:
        if STF_SEARCH_API_PATTERN.fullmatch(request.url):
            self._search_request_seen = True

    def _record_request_failure(self, request: Any) -> None:
        if not STF_SEARCH_API_PATTERN.fullmatch(request.url):
            return
        failure = request.failure or "motivo não informado"
        self._request_failures.append(f"{request.url}: {failure}")

    def _continue_search_request(self, route: Route) -> None:
        try:
            self._validate_api_url(route.request.url)
            self._search_request_seen = True
            try:
                request_body = route.request.post_data_json
            except ValueError:
                request_body = None
            if not isinstance(request_body, dict):
                raise STFResponseValidationError(
                    "O portal enviou a pesquisa em formato inesperado."
                )
            request_body["from"] = self._result_offset
            request_body["size"] = self._page_size

            bool_query = self._find_bool_query(request_body)
            if bool_query is None:
                if self._extra_filters:
                    raise STFResponseValidationError(
                        "O portal mudou o formato da pesquisa; os filtros de data e "
                        "classe não puderam ser aplicados."
                    )
            else:
                filters = bool_query.setdefault("filter", [])
                if not isinstance(filters, list):
                    raise STFResponseValidationError(
                        "O portal enviou filtros de pesquisa em formato inesperado."
                    )
                filters.extend(self._extra_filters)
            route.continue_(post_data=json.dumps(request_body, ensure_ascii=False))
        except STFResponseValidationError as error:
            self._route_error = str(error)
            route.abort("blockedbyclient")

    @staticmethod
    def _validate_api_url(url: str) -> None:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "jurisprudencia.stf.jus.br"
            or parsed.path.rstrip("/") != STF_SEARCH_API_FRAGMENT
        ):
            raise STFResponseValidationError(
                "A pesquisa tentou acessar um endereço que não pertence ao portal oficial do STF."
            )

    @staticmethod
    def _validate_pdf_url(url: str | None, index: int) -> None:
        if url is None:
            return
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_PDF_HOSTS:
            raise STFResponseValidationError(
                f"O resultado {index + 1} contém um link de PDF fora dos domínios oficiais permitidos."
            )

    @staticmethod
    def _find_bool_query(payload: dict[str, Any]) -> dict[str, Any] | None:
        query = payload.get("query")
        function_score = query.get("function_score") if isinstance(query, dict) else None
        inner_query = (
            function_score.get("query") if isinstance(function_score, dict) else None
        )
        bool_query = inner_query.get("bool") if isinstance(inner_query, dict) else None
        return bool_query if isinstance(bool_query, dict) else None

    @staticmethod
    def _validate_search_response(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise STFResponseValidationError(
                "A resposta do STF não é um objeto JSON."
            )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise STFResponseValidationError(
                "A resposta do STF não contém o objeto de resultados esperado."
            )
        hits_container = result.get("hits")
        if not isinstance(hits_container, dict):
            raise STFResponseValidationError(
                "A resposta do STF não contém a lista de documentos esperada."
            )
        hits = hits_container.get("hits")
        if not isinstance(hits, list):
            raise STFResponseValidationError(
                "A resposta do STF não contém uma lista válida de documentos."
            )
        for index, hit in enumerate(hits):
            if not isinstance(hit, dict) or not isinstance(hit.get("_source"), dict):
                raise STFResponseValidationError(
                    f"O resultado {index + 1} do STF está malformado."
                )
        return hits

    @staticmethod
    def _build_search_url(
        *, base: str, query: str, page: int, page_size: int
    ) -> str:
        params = {
            "base": base,
            "pesquisa_inteiro_teor": "false",
            "sinonimo": "true",
            "plural": "true",
            "radicais": "false",
            "buscaExata": "true",
            "page": str(page + 1),
            "pageSize": str(page_size),
            "queryString": query,
            "sort": "_score",
            "sortBy": "desc",
        }
        return f"{STF_SEARCH_PAGE}?{urlencode(params)}"

    @staticmethod
    def _build_extra_filters(
        date_from: date | None,
        date_to: date | None,
        process_class: str | None,
    ) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = []
        date_range: dict[str, str] = {}
        if date_from:
            date_range["gte"] = date_from.isoformat()
        if date_to:
            date_range["lte"] = date_to.isoformat()
        if date_range:
            filters.append({"range": {"publicacao_data": date_range}})
        if process_class:
            filters.append(
                {
                    "match_phrase": {
                        "processo_classe_processual_unificada_sigla": process_class
                    }
                }
            )
        return filters