"""
Unified upload endpoint — auto-routes based on file type.

CSV/Excel → SQLite (time series via ingestion pipeline)
PDF/DOCX/TXT/MD → Qdrant (document embeddings via document upload)
"""

import logging
import os
import tempfile
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app.config import get_settings
from app.services.connectors.base import ParsedObservation
from app.services.ingestion import get_ingestion_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["Upload"])

TIMESERIES_EXTENSIONS = {".csv", ".xlsx", ".xls"}


@router.post("/")
async def unified_upload(
    file: UploadFile = File(...),
    source: Optional[str] = Form(None),
):
    """
    Upload a CSV/Excel file — parsed as time series data → stored in SQLite.

    CSV format: wide (date, col1, col2...) or long (date, series_id, value).
    """
    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in TIMESERIES_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"This endpoint is for time series data only ({', '.join(TIMESERIES_EXTENSIONS)}). "
                   f"For documents, use the document upload feature."
        )

    settings = get_settings()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content)/1024/1024:.1f} MB). Max: {settings.MAX_UPLOAD_SIZE_MB} MB"
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        if ext == ".csv":
            df = pd.read_csv(tmp_path)
        else:
            df = pd.read_excel(tmp_path)

        observations = []

        # Detect format: long (date, series_id, value) or wide (date, col1, col2...)
        if "series_id" in df.columns and "value" in df.columns:
            date_col = [c for c in df.columns if "date" in c.lower()][0]
            for _, row in df.iterrows():
                try:
                    date_val = pd.to_datetime(row[date_col]).date()
                    value = float(row["value"]) if pd.notna(row["value"]) else None
                    observations.append(ParsedObservation(
                        series_id=str(row["series_id"]),
                        date=date_val,
                        value=value,
                    ))
                except (ValueError, TypeError):
                    continue
        else:
            # Wide format
            date_col = df.columns[0]
            for col in df.columns[1:]:
                series_id = str(col).strip()
                for _, row in df.iterrows():
                    try:
                        date_val = pd.to_datetime(row[date_col]).date()
                        value = float(row[col]) if pd.notna(row[col]) else None
                        observations.append(ParsedObservation(
                            series_id=series_id,
                            date=date_val,
                            value=value,
                        ))
                    except (ValueError, TypeError):
                        continue

        if not observations:
            raise HTTPException(status_code=400, detail="No valid time series data found in file")

        service = get_ingestion_service()
        run_id = await service._create_run(source or "Manual", "File Upload")
        load_result = await service.load_observations(observations, run_id)
        await service._finish_run(
            run_id=run_id,
            status="success",
            rows_inserted=load_result["inserted"],
            rows_updated=load_result["updated"],
            rows_skipped=load_result["skipped"],
            file_path=file.filename,
        )

        series_ids = list(set(obs.series_id for obs in observations))

        return {
            "type": "timeseries",
            "filename": file.filename,
            "source": source or "Manual",
            "series_found": series_ids,
            "rows_inserted": load_result["inserted"],
            "rows_updated": load_result["updated"],
            "rows_skipped": load_result["skipped"],
            "total": load_result["total"],
            "status": "success",
        }
    finally:
        os.unlink(tmp_path)

