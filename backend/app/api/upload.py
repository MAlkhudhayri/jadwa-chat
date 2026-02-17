"""
Unified upload endpoint — smart auto-routing.

CSV/Excel → auto-detect columns → SQLite (tagged with collection)
PDF/DOCX/TXT/MD → Qdrant document embeddings (in the collection)

No hardcoded fields. Fully automated.
"""

import json
import logging
import os
import re
import tempfile
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app.config import get_settings
from app.services.connectors.base import ParsedObservation
from app.services.ingestion import get_ingestion_service
from app.services.vectorstore import get_vectorstore_service
from app.core.database import get_session_factory
from app.models.timeseries import SeriesCatalog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["Upload"])

TIMESERIES_EXTENSIONS = {".csv", ".xlsx", ".xls"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
ALL_EXTENSIONS = TIMESERIES_EXTENSIONS | DOCUMENT_EXTENSIONS


def _slugify(text: str) -> str:
    """Convert column name to a clean series_id."""
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s


def _detect_date_column(df: pd.DataFrame) -> Optional[str]:
    """Auto-detect the most likely date column."""
    # 1. Check column names that suggest dates
    date_keywords = ["date", "period", "month", "year", "time", "day", "timestamp"]
    for col in df.columns:
        if any(kw in col.lower() for kw in date_keywords):
            try:
                pd.to_datetime(df[col].dropna().head(10))
                return col
            except Exception:
                continue

    # 2. Try the first column (common pattern)
    try:
        pd.to_datetime(df.iloc[:, 0].dropna().head(10))
        return df.columns[0]
    except Exception:
        pass

    # 3. Try all columns
    for col in df.columns:
        try:
            parsed = pd.to_datetime(df[col].dropna().head(10))
            if parsed is not None:
                return col
        except Exception:
            continue

    return None


def _detect_numeric_columns(df: pd.DataFrame, date_col: str) -> list:
    """Find all numeric columns (excluding the date column)."""
    numeric_cols = []
    for col in df.columns:
        if col == date_col:
            continue
        # Try to coerce to numeric
        try:
            numeric_data = pd.to_numeric(df[col], errors="coerce")
            # If at least 50% of non-null values are numeric, treat as numeric
            if numeric_data.notna().sum() > 0:
                ratio = numeric_data.notna().sum() / df[col].notna().sum() if df[col].notna().sum() > 0 else 0
                if ratio > 0.5:
                    numeric_cols.append(col)
        except Exception:
            continue
    return numeric_cols


async def _auto_register_series(
    series_id: str,
    name: str,
    collection_name: str,
    filename: str,
):
    """Auto-create a series_catalog entry if it doesn't exist."""
    factory = await get_session_factory()
    session = factory()
    try:
        from sqlalchemy import select
        existing = await session.execute(
            select(SeriesCatalog).where(SeriesCatalog.series_id == series_id)
        )
        if existing.scalar():
            return  # Already exists

        new_series = SeriesCatalog(
            series_id=series_id,
            name=name,
            domain=collection_name,
            source="Upload",
            dataset=filename,
            description=f"Auto-imported from {filename}, column: {name}",
            synonyms=json.dumps([name.lower(), series_id.replace("_", " ")]),
            collection_name=collection_name,
        )
        session.add(new_series)
        await session.commit()
        logger.info(f"Auto-registered series: {series_id} in {collection_name}")
    except Exception as e:
        logger.warning(f"Failed to register series {series_id}: {e}")
        await session.rollback()
    finally:
        await session.close()


@router.post("/")
async def unified_upload(
    file: UploadFile = File(...),
    collection_name: str = Form(...),
    source: Optional[str] = Form(None),
):
    """
    Smart upload endpoint.

    - CSV/Excel → auto-detects date + numeric columns → stores in SQLite
    - PDF/DOCX/TXT/MD → stores document embeddings in Qdrant

    No hardcoded fields. Column names become series names automatically.
    """
    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in ALL_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(ALL_EXTENSIONS))}",
        )

    settings = get_settings()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content)/1024/1024:.1f} MB). Max: {settings.MAX_UPLOAD_SIZE_MB} MB"
        )

    try:
        # ─── DOCUMENT PATH ─────────────────────────────────
        if ext in DOCUMENT_EXTENSIONS:
            return await _handle_document_upload(content, file.filename, collection_name, ext)

        # ─── TIME SERIES PATH ──────────────────────────────
        return await _handle_timeseries_upload(content, file.filename, collection_name, source, ext)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


async def _handle_document_upload(
    content: bytes, filename: str, collection_name: str, ext: str
):
    """Process document → chunk → embed → store in Qdrant."""
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Read document text
        if ext == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(tmp_path)
                text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            except ImportError:
                text = content.decode("utf-8", errors="ignore")
        elif ext in (".txt", ".md"):
            text = content.decode("utf-8", errors="ignore")
        elif ext == ".docx":
            try:
                import docx
                doc = docx.Document(tmp_path)
                text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except ImportError:
                text = content.decode("utf-8", errors="ignore")
        else:
            text = content.decode("utf-8", errors="ignore")

        if not text.strip():
            raise HTTPException(status_code=400, detail="No text content found in document")

        # Chunk the text
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        chunks = splitter.split_text(text)

        documents = [
            Document(
                page_content=chunk,
                metadata={
                    "source": filename,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "collection": collection_name,
                },
            )
            for i, chunk in enumerate(chunks)
        ]

        # Store in Qdrant
        vs = get_vectorstore_service()
        num_added = await vs.add_documents(collection_name, documents)

        return {
            "type": "document",
            "filename": filename,
            "collection_name": collection_name,
            "chunks_created": num_added,
            "status": "success",
        }
    finally:
        os.unlink(tmp_path)


async def _handle_timeseries_upload(
    content: bytes, filename: str, collection_name: str,
    source: Optional[str], ext: str
):
    """Smart CSV/Excel processing — auto-detect everything."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Read file
        if ext == ".csv":
            df = pd.read_csv(tmp_path)
        else:
            df = pd.read_excel(tmp_path)

        if df.empty:
            raise HTTPException(status_code=400, detail="File is empty")

        # Auto-detect date column
        date_col = _detect_date_column(df)
        if not date_col:
            raise HTTPException(
                status_code=400,
                detail=f"Could not detect a date column. Found columns: {list(df.columns)}. "
                       "Please ensure one column contains dates."
            )

        # Auto-detect numeric columns
        numeric_cols = _detect_numeric_columns(df, date_col)
        if not numeric_cols:
            raise HTTPException(
                status_code=400,
                detail=f"No numeric columns found (besides date column '{date_col}'). "
                       f"Found columns: {list(df.columns)}"
            )

        # Parse dates
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])

        # Build observations and auto-register series
        observations = []
        series_created = []

        for col in numeric_cols:
            # Generate unique series_id scoped to this collection
            raw_slug = _slugify(col)
            series_id = f"{_slugify(collection_name)}__{raw_slug}"

            # Auto-register this series in the catalog
            await _auto_register_series(
                series_id=series_id,
                name=col.strip(),
                collection_name=collection_name,
                filename=filename,
            )
            series_created.append({"series_id": series_id, "column": col})

            # Convert column to numeric
            numeric_data = pd.to_numeric(df[col], errors="coerce")

            for _, row in df.iterrows():
                try:
                    date_val = row[date_col].date()
                    value = float(numeric_data[row.name]) if pd.notna(numeric_data[row.name]) else None
                    observations.append(ParsedObservation(
                        series_id=series_id,
                        date=date_val,
                        value=value,
                    ))
                except (ValueError, TypeError, AttributeError):
                    continue

        if not observations:
            raise HTTPException(status_code=400, detail="No valid data rows found in file")

        # Load into SQLite
        service = get_ingestion_service()
        run_id = await service._create_run(source or "Upload", filename)
        load_result = await service.load_observations(observations, run_id)
        await service._finish_run(
            run_id=run_id,
            status="success",
            rows_inserted=load_result["inserted"],
            rows_updated=load_result["updated"],
            rows_skipped=load_result["skipped"],
            file_path=filename,
        )

        return {
            "type": "timeseries",
            "filename": filename,
            "collection_name": collection_name,
            "date_column": date_col,
            "series_detected": series_created,
            "rows_inserted": load_result["inserted"],
            "rows_updated": load_result["updated"],
            "rows_skipped": load_result["skipped"],
            "total": load_result["total"],
            "status": "success",
        }
    finally:
        os.unlink(tmp_path)
