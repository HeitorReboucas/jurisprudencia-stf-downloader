from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.config import Settings
from app.organizer import FOLDER_NAMES


DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


class DriveIntegrationError(RuntimeError):
    pass


class GoogleDriveClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pending_flows: dict[str, Flow] = {}

    def is_configured(self) -> bool:
        return self.settings.google_client_secrets_file.is_file()

    def is_authorized(self) -> bool:
        return self.settings.token_path.is_file()

    def create_authorization_url(self) -> str:
        secrets_path = self.settings.google_client_secrets_file
        if not secrets_path.is_file():
            raise DriveIntegrationError(
                f"Arquivo OAuth não encontrado: {secrets_path}. Configure-o conforme o README."
            )

        flow = Flow.from_client_secrets_file(str(secrets_path), scopes=[DRIVE_SCOPE])
        flow.redirect_uri = self.settings.google_redirect_uri
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        self.pending_flows[state] = flow
        return authorization_url

    def complete_authorization(self, code: str, state: str) -> None:
        flow = self.pending_flows.pop(state, None)
        if flow is None:
            raise DriveIntegrationError("Estado OAuth inválido ou expirado; inicie a autorização novamente.")
        flow.fetch_token(code=code)
        token_path = self.settings.token_path
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(flow.credentials.to_json(), encoding="utf-8")

    def list_folders(self) -> list[dict[str, str]]:
        service = self._service()
        folders: list[dict[str, str]] = []
        page_token = None
        while True:
            response = (
                service.files()
                .list(
                    q=f"mimeType = '{FOLDER_MIME_TYPE}' and trashed = false",
                    spaces="drive",
                    fields="nextPageToken, files(id, name)",
                    pageSize=1000,
                    orderBy="name",
                    pageToken=page_token,
                )
                .execute()
            )
            folders.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return folders

    def upload_pdf(self, file_path: Path, folder_id: str, document_key: str) -> str:
        service = self._service()
        escaped_key = document_key.replace("\\", "\\\\").replace("'", "\\'")
        escaped_folder = folder_id.replace("\\", "\\\\").replace("'", "\\'")
        existing = (
            service.files()
            .list(
                q=(
                    "appProperties has { key='stf_document_key' and "
                    f"value='{escaped_key}' }} and '{escaped_folder}' in parents "
                    "and trashed = false"
                ),
                spaces="drive",
                fields="files(id)",
                pageSize=1,
            )
            .execute()
            .get("files", [])
        )
        if existing:
            return existing[0]["id"]

        media = MediaFileUpload(str(file_path), mimetype="application/pdf", resumable=True)
        uploaded = (
            service.files()
            .create(
                body={
                    "name": file_path.name,
                    "parents": [folder_id],
                    "appProperties": {"stf_document_key": document_key},
                },
                media_body=media,
                fields="id",
            )
            .execute()
        )
        return uploaded["id"]

    def ensure_archive_folder(
        self,
        root_folder_id: str,
        content_type: str,
        document_date: str | None,
    ) -> str:
        year = document_date[:4] if document_date else "sem_data"
        folder_id = self._find_or_create_folder("STF", root_folder_id)
        folder_id = self._find_or_create_folder(FOLDER_NAMES[content_type], folder_id)
        return self._find_or_create_folder(year, folder_id)

    def _find_or_create_folder(self, name: str, parent_id: str) -> str:
        service = self._service()
        escaped_name = name.replace("\\", "\\\\").replace("'", "\\'")
        escaped_parent = parent_id.replace("\\", "\\\\").replace("'", "\\'")
        existing = (
            service.files()
            .list(
                q=(
                    f"name = '{escaped_name}' and '{escaped_parent}' in parents "
                    f"and mimeType = '{FOLDER_MIME_TYPE}' and trashed = false"
                ),
                spaces="drive",
                fields="files(id)",
                pageSize=1,
            )
            .execute()
            .get("files", [])
        )
        if existing:
            return existing[0]["id"]
        created = (
            service.files()
            .create(
                body={
                    "name": name,
                    "mimeType": FOLDER_MIME_TYPE,
                    "parents": [parent_id],
                },
                fields="id",
            )
            .execute()
        )
        return created["id"]

    def _service(self) -> Any:
        credentials = self._credentials()
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    def _credentials(self) -> Credentials:
        token_path = self.settings.token_path
        if not token_path.is_file():
            raise DriveIntegrationError("Google Drive não autorizado. Inicie o fluxo OAuth primeiro.")

        credentials = Credentials.from_authorized_user_file(str(token_path), [DRIVE_SCOPE])
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            token_path.write_text(credentials.to_json(), encoding="utf-8")
        if not credentials.valid:
            raise DriveIntegrationError("Credenciais Google expiradas. Autorize o Drive novamente.")
        return credentials