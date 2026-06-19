"""Google Drive tool executor - list, read, create and share Drive files."""
from __future__ import annotations
import json, logging, os
from typing import Any
logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

def _build_service(service_name: str, version: str):
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not configured.")
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build as gdisco_build
    except ImportError:
        raise RuntimeError("google-api-python-client not installed. Add to requirements: pip install google-api-python-client google-auth")
    info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    delegate = os.getenv("GOOGLE_DRIVE_DELEGATE_EMAIL")
    if delegate:
        creds = creds.with_subject(delegate)
    return gdisco_build(service_name, version, credentials=creds, cache_discovery=False)

_MIME_TEXT = {
    "application/vnd.google-apps.document": ("text/plain", "docs", "v1", "documents"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", "sheets", "v4", "spreadsheets"),
}

async def execute(args: dict, chat_id: str, agent_id: Any, agent_name: Any) -> dict:
    import asyncio
    from src.core.pubsub import broadcast as _broadcast
    action = (args.get("action") or "").strip()
    if not action:
        return {"error": "action is required. Valid: list_files, get_file, read_file, create_doc, upload_file, share_file"}
    await _broadcast(chat_id, {"type": "activity_status", "status": "running", "tool": "google_drive", "label": f"Google Drive {action}..."})

    def _run(fn):
        return asyncio.get_event_loop().run_in_executor(None, fn)

    try:
        if action == "list_files":
            def _do():
                svc = _build_service("drive", "v3")
                q = args.get("query", "")
                folder_id = args.get("folder_id")
                if folder_id:
                    base_q = f"'{folder_id}' in parents and trashed=false"
                    q = f"{base_q} and {q}" if q else base_q
                elif not q:
                    q = "trashed=false"
                params = {
                    "q": q,
                    "pageSize": min(int(args.get("limit", 50)), 200),
                    "fields": "files(id,name,mimeType,size,modifiedTime,webViewLink,parents)",
                    "orderBy": args.get("order_by", "modifiedTime desc"),
                }
                resp = svc.files().list(**params).execute()
                files = [
                    {
                        "id": f["id"], "name": f["name"],
                        "mime_type": f.get("mimeType"),
                        "size": f.get("size"),
                        "modified": f.get("modifiedTime"),
                        "url": f.get("webViewLink"),
                    }
                    for f in resp.get("files", [])
                ]
                return {"data": {"files": files, "count": len(files)}}
            return await _run(_do)

        elif action == "get_file":
            file_id = args.get("file_id")
            if not file_id:
                return {"error": "file_id required"}
            def _do():
                svc = _build_service("drive", "v3")
                f = svc.files().get(fileId=file_id, fields="id,name,mimeType,size,modifiedTime,webViewLink,parents,description").execute()
                return {"data": {
                    "id": f["id"], "name": f["name"],
                    "mime_type": f.get("mimeType"), "size": f.get("size"),
                    "modified": f.get("modifiedTime"), "url": f.get("webViewLink"),
                    "description": f.get("description"), "parents": f.get("parents", []),
                }}
            return await _run(_do)

        elif action == "read_file":
            file_id = args.get("file_id")
            if not file_id:
                return {"error": "file_id required"}
            def _do():
                svc = _build_service("drive", "v3")
                meta = svc.files().get(fileId=file_id, fields="id,name,mimeType,size").execute()
                mime = meta.get("mimeType", "")
                name = meta.get("name", "")
                if mime == "application/vnd.google-apps.document":
                    raw = svc.files().export(fileId=file_id, mimeType="text/plain").execute()
                    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                    return {"data": {"id": file_id, "name": name, "content": text[:100_000], "mime_type": mime}}
                elif mime == "application/vnd.google-apps.spreadsheet":
                    raw = svc.files().export(fileId=file_id, mimeType="text/csv").execute()
                    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                    return {"data": {"id": file_id, "name": name, "content": text[:100_000], "mime_type": mime}}
                elif mime.startswith("text/") or name.endswith((".txt", ".md", ".json", ".yaml", ".yml", ".csv", ".py", ".js")):
                    raw = svc.files().get_media(fileId=file_id).execute()
                    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                    return {"data": {"id": file_id, "name": name, "content": text[:100_000], "mime_type": mime}}
                else:
                    size = meta.get("size", 0)
                    return {"data": {"id": file_id, "name": name, "mime_type": mime, "size": size, "note": "Binary file - use get_file for download URL"}}
            return await _run(_do)

        elif action == "create_doc":
            title = args.get("title", "Untitled")
            content = args.get("content", "")
            doc_type = args.get("type", "doc")
            def _do():
                svc = _build_service("drive", "v3")
                mime = "application/vnd.google-apps.document" if doc_type == "doc" else "application/vnd.google-apps.spreadsheet"
                meta: dict[str, Any] = {"name": title, "mimeType": mime}
                folder_id = args.get("folder_id")
                if folder_id:
                    meta["parents"] = [folder_id]
                f = svc.files().create(body=meta, fields="id,name,webViewLink").execute()
                result = {"id": f["id"], "name": f["name"], "url": f.get("webViewLink")}
                if content and doc_type == "doc":
                    try:
                        docs_svc = _build_service("docs", "v1")
                        docs_svc.documents().batchUpdate(
                            documentId=f["id"],
                            body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
                        ).execute()
                    except Exception:
                        pass
                return {"data": result}
            return await _run(_do)

        elif action == "upload_file":
            name = args.get("name")
            content = args.get("content")
            if not name or content is None:
                return {"error": "name and content required"}
            def _do():
                import io
                from googleapiclient.http import MediaIoBaseUpload
                svc = _build_service("drive", "v3")
                ct = args.get("content_type", "text/plain")
                meta: dict[str, Any] = {"name": name}
                folder_id = args.get("folder_id")
                if folder_id:
                    meta["parents"] = [folder_id]
                body_bytes = content.encode("utf-8") if isinstance(content, str) else content
                media = MediaIoBaseUpload(io.BytesIO(body_bytes), mimetype=ct, resumable=False)
                f = svc.files().create(body=meta, media_body=media, fields="id,name,webViewLink,size").execute()
                return {"data": {"id": f["id"], "name": f["name"], "url": f.get("webViewLink"), "size": f.get("size")}}
            return await _run(_do)

        elif action == "share_file":
            file_id = args.get("file_id")
            email = args.get("email")
            role = args.get("role", "reader")
            if not file_id or not email:
                return {"error": "file_id and email required"}
            def _do():
                svc = _build_service("drive", "v3")
                perm = {"type": "user", "role": role, "emailAddress": email}
                svc.permissions().create(fileId=file_id, body=perm, sendNotificationEmail=bool(args.get("notify", False))).execute()
                return {"data": {"file_id": file_id, "shared_with": email, "role": role}}
            return await _run(_do)

        else:
            return {"error": "Unknown action. Valid: list_files, get_file, read_file, create_doc, upload_file, share_file"}

    except RuntimeError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Google Drive error: {e}"}