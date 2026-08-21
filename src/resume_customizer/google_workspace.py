"""Google Drive helpers: PDF export, folder, copy. Docs get/batchUpdate."""

from __future__ import annotations

from typing import Any

from resume_customizer.google_docs_ops import RESUME_CUSTOMIZER_FOLDER

PDF_EXPORT_MIME = "application/pdf"
_FOLDER_MIME = "application/vnd.google-apps.folder"


class GoogleWorkspaceError(RuntimeError):
    """Drive or Docs API failure."""


def export_pdf(drive: Any, file_id: str) -> bytes:
    """Export a Google Doc as PDF bytes via Drive ``files.export``.

    Args:
        drive: Drive API v3 resource (``build("drive", "v3", ...)``).
        file_id: Drive file id of a Google Doc.

    Returns:
        PDF file contents.

    Raises:
        GoogleWorkspaceError: If export fails or the body is empty.
    """
    try:
        data = drive.files().export(fileId=file_id, mimeType=PDF_EXPORT_MIME).execute()
    except Exception as exc:
        raise GoogleWorkspaceError(f"Could not export Google Doc to PDF: {exc}") from exc
    if not data:
        raise GoogleWorkspaceError("Google PDF export returned empty content.")
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    return bytes(data)


def find_or_create_folder(drive: Any, name: str = RESUME_CUSTOMIZER_FOLDER) -> str:
    """Return the id of an app-visible folder named ``name``, creating it if needed.

    Args:
        drive: Drive API v3 resource.
        name: Folder name (default ``ResumeCustomizer``).

    Returns:
        Folder file id.

    Raises:
        GoogleWorkspaceError: If list or create fails.
    """
    query = f"name = '{name}' and mimeType = '{_FOLDER_MIME}' and trashed = false"
    try:
        listed = (
            drive.files()
            .list(q=query, spaces="drive", fields="files(id, name)", pageSize=10)
            .execute()
        )
    except Exception as exc:
        raise GoogleWorkspaceError(f"Could not search Drive for folder {name!r}: {exc}") from exc
    files = listed.get("files") if isinstance(listed, dict) else None
    if files:
        folder_id = files[0].get("id")
        if folder_id:
            return str(folder_id)
    try:
        created = (
            drive.files()
            .create(
                body={"name": name, "mimeType": _FOLDER_MIME},
                fields="id",
            )
            .execute()
        )
    except Exception as exc:
        raise GoogleWorkspaceError(f"Could not create Drive folder {name!r}: {exc}") from exc
    folder_id = created.get("id") if isinstance(created, dict) else None
    if not folder_id:
        raise GoogleWorkspaceError(f"Create folder {name!r} returned no id.")
    return str(folder_id)


def copy_doc_into_folder(
    drive: Any,
    *,
    file_id: str,
    folder_id: str,
    name: str,
) -> dict[str, str]:
    """Copy a Doc into ``folder_id`` and return id, name, and webViewLink.

    Args:
        drive: Drive API v3 resource.
        file_id: Source Google Doc id (never mutated).
        folder_id: Destination folder id.
        name: Name for the copy.

    Returns:
        Mapping with ``id``, ``name``, ``webViewLink``.

    Raises:
        GoogleWorkspaceError: If copy fails or the response has no id.
    """
    try:
        copied = (
            drive.files()
            .copy(
                fileId=file_id,
                body={"name": name, "parents": [folder_id]},
                fields="id,name,webViewLink",
            )
            .execute()
        )
    except Exception as exc:
        raise GoogleWorkspaceError(f"Could not copy Google Doc: {exc}") from exc
    copy_id = copied.get("id") if isinstance(copied, dict) else None
    if not copy_id:
        raise GoogleWorkspaceError("Drive copy returned no document id.")
    return {
        "id": str(copy_id),
        "name": str(copied.get("name") or name),
        "webViewLink": str(copied.get("webViewLink") or f"https://docs.google.com/document/d/{copy_id}/edit"),
    }


def get_document(docs: Any, document_id: str) -> dict[str, Any]:
    """Fetch a document resource from the Docs API.

    Raises:
        GoogleWorkspaceError: If get fails.
    """
    try:
        document = docs.documents().get(documentId=document_id).execute()
    except Exception as exc:
        raise GoogleWorkspaceError(f"Could not read Google Doc: {exc}") from exc
    if not isinstance(document, dict):
        raise GoogleWorkspaceError("Docs get returned an unexpected payload.")
    return document


def batch_update(docs: Any, document_id: str, requests: list[dict[str, Any]]) -> None:
    """Apply ``batchUpdate`` requests to ``document_id``.

    Raises:
        GoogleWorkspaceError: If the API call fails.
    """
    if not requests:
        return
    try:
        docs.documents().batchUpdate(
            documentId=document_id,
            body={"requests": requests},
        ).execute()
    except Exception as exc:
        raise GoogleWorkspaceError(f"Could not update Google Doc: {exc}") from exc
