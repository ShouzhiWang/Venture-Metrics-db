"""Source Reader — fetch and parse data from URLs, connector IDs, or snapshots.

Returns structured table packets (CSV/XLSX/JSON/HTML tables) or text packets
(PDF/HTML text) so the agent can read actual data values, not just metadata.
"""
from __future__ import annotations

import io
import json
import logging
import mimetypes
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_source(
    *,
    url: str | None = None,
    connector_dataset_id: str | None = None,
    connector_snapshot_id: str | None = None,
    connector_resource_id: str | None = None,
    external_source_candidate_id: str | None = None,
    max_rows: int = 500,
    timeout: int = 30,
) -> dict[str, Any]:
    """Read a data source and return a table packet, text packet, or metadata-only packet.

    Input can be a direct URL or a connector ID. When an ID is provided the
    system resolves it to a URL via the DB, then fetches.
    """
    resolved = _resolve_source(
        url=url,
        connector_dataset_id=connector_dataset_id,
        connector_snapshot_id=connector_snapshot_id,
        connector_resource_id=connector_resource_id,
        external_source_candidate_id=external_source_candidate_id,
    )
    if not resolved.get("ok"):
        return resolved

    source_url = resolved["url"]
    title = resolved.get("title") or source_url
    content_type = resolved.get("content_type") or ""
    local_path = resolved.get("local_path")

    # If we have a local_path from a snapshot, try reading it first
    if local_path:
        return _read_local_file(local_path, title=title, source_url=source_url, max_rows=max_rows)

    # Fetch from URL
    return _fetch_and_parse(
        url=source_url,
        title=title,
        content_type_hint=content_type,
        max_rows=max_rows,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------

def _resolve_source(**kwargs: Any) -> dict[str, Any]:
    """Resolve input identifiers to a fetchable URL + metadata."""
    url = kwargs.get("url")
    dataset_id = kwargs.get("connector_dataset_id")
    snapshot_id = kwargs.get("connector_snapshot_id")
    resource_id = kwargs.get("connector_resource_id")
    candidate_id = kwargs.get("external_source_candidate_id")

    # Direct URL — simplest case
    if url:
        return {"ok": True, "url": url, "title": url, "content_type": ""}

    # Try DB resolution for IDs
    try:
        from app.db.session import get_supabase_client
        supabase = get_supabase_client()

        if snapshot_id:
            resp = supabase.table("connector_snapshots").select("*").eq("id", snapshot_id).limit(1).execute()
            if resp.data:
                snap = resp.data[0]
                local_path = snap.get("local_path")
                dataset_resp = supabase.table("connector_datasets").select("name,source_url").eq("id", snap["dataset_id"]).limit(1).execute()
                ds_name = dataset_resp.data[0]["name"] if dataset_resp.data else "Snapshot"
                ds_url = dataset_resp.data[0].get("source_url", "") if dataset_resp.data else ""
                return {
                    "ok": True,
                    "url": ds_url,
                    "title": ds_name,
                    "content_type": "",
                    "local_path": local_path,
                    "snapshot_metadata": {
                        "row_count": snap.get("row_count"),
                        "column_count": snap.get("column_count"),
                        "retrieved_at": str(snap.get("retrieved_at", "")),
                        "snapshot_id": snapshot_id,
                    },
                }

        if resource_id:
            resp = supabase.table("connector_resources").select("*").eq("id", resource_id).limit(1).execute()
            if resp.data:
                res = resp.data[0]
                return {
                    "ok": True,
                    "url": res.get("resource_url") or "",
                    "title": res.get("resource_name") or "Resource",
                    "content_type": res.get("format") or "",
                    "local_path": res.get("local_path"),
                }

        if dataset_id:
            resp = supabase.table("connector_datasets").select("*").eq("id", dataset_id).limit(1).execute()
            if resp.data:
                ds = resp.data[0]
                # Check for existing snapshot
                snap_resp = supabase.table("connector_snapshots").select("*").eq("dataset_id", dataset_id).order("retrieved_at", desc=True).limit(1).execute()
                local_path = snap_resp.data[0].get("local_path") if snap_resp.data else None
                return {
                    "ok": True,
                    "url": ds.get("source_url") or "",
                    "title": ds.get("name") or "Dataset",
                    "content_type": ds.get("metadata", {}).get("format") or "",
                    "local_path": local_path,
                    "snapshot_metadata": {
                        "row_count": snap_resp.data[0].get("row_count") if snap_resp.data else None,
                        "retrieved_at": str(snap_resp.data[0].get("retrieved_at", "")) if snap_resp.data else None,
                        "snapshot_id": snap_resp.data[0]["id"] if snap_resp.data else None,
                    } if snap_resp.data else None,
                }

        if candidate_id:
            resp = supabase.table("external_source_candidates").select("*").eq("id", candidate_id).limit(1).execute()
            if resp.data:
                cand = resp.data[0]
                return {
                    "ok": True,
                    "url": cand.get("url") or "",
                    "title": cand.get("title") or "Candidate source",
                    "content_type": "",
                }

    except Exception as exc:
        logger.debug("DB resolution failed: %s", exc)

    return {"ok": False, "error": {"code": "no_source", "message": "No URL or valid ID provided."}}


# ---------------------------------------------------------------------------
# Fetch + parse
# ---------------------------------------------------------------------------

def _fetch_and_parse(
    *,
    url: str,
    title: str,
    content_type_hint: str,
    max_rows: int,
    timeout: int,
) -> dict[str, Any]:
    """Fetch a URL and parse into table or text packet."""
    if not url:
        return _metadata_only_packet(title=title, source_url="", reason="No URL available to fetch.")

    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "VentureMetrics/1.0"}, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return _metadata_only_packet(title=title, source_url=url, reason=f"Fetch failed: {exc}")

    content_type = (resp.headers.get("Content-Type") or content_type_hint or "").lower()
    retrieved_at = datetime.now(timezone.utc).isoformat()

    # Detect format from URL extension or content-type
    fmt = _detect_format(url, content_type, resp.content[:200])

    if fmt in ("csv", "tsv"):
        return _parse_csv(resp.content, title=title, source_url=url, retrieved_at=retrieved_at, max_rows=max_rows, delimiter="\t" if fmt == "tsv" else ",")
    elif fmt == "xlsx":
        return _parse_xlsx(resp.content, title=title, source_url=url, retrieved_at=retrieved_at, max_rows=max_rows)
    elif fmt == "json":
        return _parse_json(resp.content, title=title, source_url=url, retrieved_at=retrieved_at, max_rows=max_rows)
    elif fmt == "html_table":
        return _parse_html_table(resp.text, title=title, source_url=url, retrieved_at=retrieved_at, max_rows=max_rows)
    elif fmt == "pdf":
        return _parse_pdf(resp.content, title=title, source_url=url, retrieved_at=retrieved_at)
    else:
        # Treat as text
        return _parse_text(resp.text, title=title, source_url=url, retrieved_at=retrieved_at)


def _detect_format(url: str, content_type: str, head_bytes: bytes) -> str:
    """Detect file format from URL, content-type, or file magic bytes."""
    url_lower = url.lower().split("?")[0].split("#")[0]

    if url_lower.endswith(".csv"):
        return "csv"
    if url_lower.endswith(".tsv"):
        return "tsv"
    if url_lower.endswith((".xlsx", ".xls")):
        return "xlsx"
    if url_lower.endswith(".pdf"):
        return "pdf"
    if url_lower.endswith(".json") or url_lower.endswith(".jsonl"):
        return "json"
    if url_lower.endswith((".htm", ".html")):
        return "html_table"

    # Content-type
    if "csv" in content_type or "text/plain" in content_type:
        return "csv"
    if "spreadsheet" in content_type or "excel" in content_type:
        return "xlsx"
    if "json" in content_type:
        return "json"
    if "pdf" in content_type:
        return "pdf"
    if "html" in content_type:
        return "html_table"

    # Magic bytes
    if head_bytes.startswith(b"PK"):
        return "xlsx"
    if head_bytes.startswith(b"%PDF"):
        return "pdf"
    if head_bytes.startswith(b"{") or head_bytes.startswith(b"["):
        return "json"

    # Check if it looks like CSV (first line has commas/tabs)
    try:
        first_line = head_bytes.decode("utf-8", errors="ignore").split("\n")[0]
        if first_line.count(",") >= 2 or first_line.count("\t") >= 2:
            return "csv"
    except Exception:
        pass

    return "text"


# ---------------------------------------------------------------------------
# Parsers — each returns a table_packet or text_packet
# ---------------------------------------------------------------------------

def _parse_csv(content: bytes, *, title: str, source_url: str, retrieved_at: str, max_rows: int, delimiter: str = ",") -> dict[str, Any]:
    """Parse CSV/TSV into a table packet."""
    try:
        import pandas as pd
        # Try utf-8 first, then latin-1
        for enc in ("utf-8", "latin-1", "utf-8-sig"):
            try:
                df = pd.read_csv(io.BytesIO(content), delimiter=delimiter, encoding=enc, nrows=max_rows, on_bad_lines="skip")
                break
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        else:
            return _metadata_only_packet(title=title, source_url=source_url, reason="Could not parse CSV — encoding or format issue.")

        return _df_to_table_packet(df, title=title, source_url=source_url, retrieved_at=retrieved_at)
    except Exception as exc:
        return _metadata_only_packet(title=title, source_url=source_url, reason=f"CSV parse error: {exc}")


def _parse_xlsx(content: bytes, *, title: str, source_url: str, retrieved_at: str, max_rows: int) -> dict[str, Any]:
    """Parse XLSX into a table packet."""
    try:
        import pandas as pd
        df = pd.read_excel(io.BytesIO(content), nrows=max_rows)
        return _df_to_table_packet(df, title=title, source_url=source_url, retrieved_at=retrieved_at)
    except Exception as exc:
        return _metadata_only_packet(title=title, source_url=source_url, reason=f"XLSX parse error: {exc}")


def _parse_json(content: bytes, *, title: str, source_url: str, retrieved_at: str, max_rows: int) -> dict[str, Any]:
    """Parse JSON (array of objects or nested) into a table packet."""
    try:
        data = json.loads(content)
        # Array of objects — direct table
        if isinstance(data, list) and data and isinstance(data[0], dict):
            import pandas as pd
            df = pd.DataFrame(data[:max_rows])
            return _df_to_table_packet(df, title=title, source_url=source_url, retrieved_at=retrieved_at)
        # Nested — try to find the array
        if isinstance(data, dict):
            for key in ("data", "results", "records", "items", "rows", "features"):
                if key in data and isinstance(data[key], list) and data[key] and isinstance(data[key][0], dict):
                    import pandas as pd
                    df = pd.DataFrame(data[key][:max_rows])
                    return _df_to_table_packet(df, title=title, source_url=source_url, retrieved_at=retrieved_at)
            # GeoJSON features
            if "features" in data and isinstance(data["features"], list):
                import pandas as pd
                rows = [f.get("properties", {}) for f in data["features"][:max_rows]]
                df = pd.DataFrame(rows)
                return _df_to_table_packet(df, title=title, source_url=source_url, retrieved_at=retrieved_at)
        return _metadata_only_packet(title=title, source_url=source_url, reason="JSON structure not recognized as tabular data.")
    except Exception as exc:
        return _metadata_only_packet(title=title, source_url=source_url, reason=f"JSON parse error: {exc}")


def _parse_html_table(html: str, *, title: str, source_url: str, retrieved_at: str, max_rows: int) -> dict[str, Any]:
    """Parse HTML tables into a table packet."""
    try:
        import pandas as pd
        tables = pd.read_html(io.StringIO(html), flavor="lxml")
        if not tables:
            return _metadata_only_packet(title=title, source_url=source_url, reason="No HTML tables found on page.")
        # Use the largest table
        df = max(tables, key=lambda t: len(t))
        df = df.head(max_rows)
        return _df_to_table_packet(df, title=title, source_url=source_url, retrieved_at=retrieved_at)
    except Exception as exc:
        return _metadata_only_packet(title=title, source_url=source_url, reason=f"HTML table parse error: {exc}")


def _parse_pdf(content: bytes, *, title: str, source_url: str, retrieved_at: str) -> dict[str, Any]:
    """Extract text from PDF."""
    try:
        import fitz
        doc = fitz.open(stream=content, filetype="pdf")
        chunks = []
        for i, page in enumerate(doc):
            text = page.get_text()
            if text.strip():
                chunks.append({"page": i + 1, "text": text.strip()[:3000]})
        doc.close()
        return {
            "packet_type": "text",
            "title": title,
            "source_url": source_url,
            "retrieved_at": retrieved_at,
            "chunks": chunks[:20],
            "total_pages": len(chunks),
            "evidence_level": "text_evidence_read",
        }
    except Exception as exc:
        return _metadata_only_packet(title=title, source_url=source_url, reason=f"PDF parse error: {exc}")


def _parse_text(html: str, *, title: str, source_url: str, retrieved_at: str) -> dict[str, Any]:
    """Extract text from HTML or plain text."""
    try:
        from lxml import etree
        # Strip HTML tags
        doc = etree.HTML(html)
        # Remove script/style
        for tag in doc.xpath("//script | //style"):
            tag.getparent().remove(tag)
        text = etree.tostring(doc, method="text", encoding="unicode").strip()
        # Chunk it
        words = text.split()
        chunks = []
        chunk_size = 500
        for i in range(0, min(len(words), chunk_size * 20), chunk_size):
            chunk_text = " ".join(words[i:i + chunk_size])
            if chunk_text.strip():
                chunks.append({"chunk_id": len(chunks) + 1, "text": chunk_text[:3000]})
        return {
            "packet_type": "text",
            "title": title,
            "source_url": source_url,
            "retrieved_at": retrieved_at,
            "chunks": chunks[:20],
            "evidence_level": "text_evidence_read",
        }
    except Exception:
        # Fallback: just return raw text
        return {
            "packet_type": "text",
            "title": title,
            "source_url": source_url,
            "retrieved_at": retrieved_at,
            "chunks": [{"chunk_id": 1, "text": html[:5000]}],
            "evidence_level": "text_evidence_read",
        }


# ---------------------------------------------------------------------------
# Local file reader
# ---------------------------------------------------------------------------

def _read_local_file(path: str, *, title: str, source_url: str, max_rows: int) -> dict[str, Any]:
    """Read from a local file path (snapshot)."""
    import os
    if not os.path.exists(path):
        return _metadata_only_packet(title=title, source_url=source_url, reason=f"Local file not found: {path}")

    retrieved_at = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat()
    fmt = _detect_format(path, "", open(path, "rb").read(200))

    try:
        with open(path, "rb") as f:
            content = f.read()
        if fmt in ("csv", "tsv"):
            return _parse_csv(content, title=title, source_url=source_url, retrieved_at=retrieved_at, max_rows=max_rows, delimiter="\t" if fmt == "tsv" else ",")
        elif fmt == "xlsx":
            return _parse_xlsx(content, title=title, source_url=source_url, retrieved_at=retrieved_at, max_rows=max_rows)
        elif fmt == "json":
            return _parse_json(content, title=title, source_url=source_url, retrieved_at=retrieved_at, max_rows=max_rows)
        elif fmt == "pdf":
            return _parse_pdf(content, title=title, source_url=source_url, retrieved_at=retrieved_at)
        else:
            return _parse_text(content.decode("utf-8", errors="ignore"), title=title, source_url=source_url, retrieved_at=retrieved_at)
    except Exception as exc:
        return _metadata_only_packet(title=title, source_url=source_url, reason=f"Local file read error: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df_to_table_packet(df: "pd.DataFrame", *, title: str, source_url: str, retrieved_at: str) -> dict[str, Any]:
    """Convert a pandas DataFrame to a table_packet."""
    import pandas as pd
    columns = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        columns.append({
            "name": str(col),
            "dtype": dtype,
            "non_null_count": int(df[col].notna().sum()),
            "sample_values": [str(v) for v in df[col].dropna().head(3).tolist()],
        })

    rows_sample = []
    for _, row in df.head(20).iterrows():
        rows_sample.append({str(k): (str(v) if pd.notna(v) else None) for k, v in row.items()})

    return {
        "packet_type": "table",
        "title": title,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": columns,
        "rows_sample": rows_sample,
        "full_rows": rows_sample if len(df) <= 50 else None,
        "evidence_level": "table_values_read",
    }


def _metadata_only_packet(*, title: str, source_url: str, reason: str) -> dict[str, Any]:
    """Return when we can't read actual data."""
    return {
        "packet_type": "metadata_only",
        "title": title,
        "source_url": source_url,
        "reason": reason,
        "evidence_level": "metadata_only",
    }
