import logging
import os
import tempfile
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from app.config import get_settings
from app.services.vectorstore import get_vectorstore_service
from app.models.schemas import DocumentUploadResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])

# Supported file types
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".csv"}


def _load_file(file_path: str, filename: str) -> List[Document]:
    """Load a file and return LangChain Documents."""
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".pdf":
        from langchain_community.document_loaders import PyPDFLoader
        loader = PyPDFLoader(file_path)
        return loader.load()

    elif ext == ".docx":
        from langchain_community.document_loaders import Docx2txtLoader
        loader = Docx2txtLoader(file_path)
        return loader.load()

    elif ext == ".csv":
        from langchain_community.document_loaders import CSVLoader
        loader = CSVLoader(file_path)
        return loader.load()

    elif ext in {".txt", ".md"}:
        from langchain_community.document_loaders import TextLoader
        loader = TextLoader(file_path, encoding="utf-8")
        return loader.load()

    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _chunk_documents(documents: List[Document]) -> List[Document]:
    """Split documents into chunks."""
    settings = get_settings()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_documents(documents)


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    collection_name: str = Form(...),
):
    """Upload a document to a specific collection."""
    # Validate file extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    # Enforce file size limit
    settings = get_settings()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content) / 1024 / 1024:.1f} MB). Maximum: {settings.MAX_UPLOAD_SIZE_MB} MB",
        )

    try:
        # Save uploaded file to temp directory
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # Load and chunk the document
            raw_docs = _load_file(tmp_path, file.filename)

            # Add source metadata
            for doc in raw_docs:
                doc.metadata["source"] = file.filename
                doc.metadata["collection"] = collection_name

            chunks = _chunk_documents(raw_docs)
            logger.info(
                f"File '{file.filename}' → {len(raw_docs)} pages → {len(chunks)} chunks"
            )

            # Add to vector store (runs in thread pool)
            vs = get_vectorstore_service()
            count = await vs.add_documents(collection_name, chunks)

            return DocumentUploadResponse(
                filename=file.filename,
                collection_name=collection_name,
                chunks_created=count,
            )
        finally:
            os.unlink(tmp_path)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process document: {e}")


@router.post("/upload-multiple", response_model=List[DocumentUploadResponse])
async def upload_multiple_documents(
    files: List[UploadFile] = File(...),
    collection_name: str = Form(...),
):
    """Upload multiple documents to a collection."""
    settings = get_settings()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    results = []
    errors = []

    for file in files:
        try:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                errors.append(f"{file.filename}: unsupported type {ext}")
                continue

            content = await file.read()
            if len(content) > max_bytes:
                errors.append(f"{file.filename}: too large ({len(content) / 1024 / 1024:.1f} MB)")
                continue

            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            try:
                raw_docs = _load_file(tmp_path, file.filename)
                for doc in raw_docs:
                    doc.metadata["source"] = file.filename
                    doc.metadata["collection"] = collection_name

                chunks = _chunk_documents(raw_docs)
                vs = get_vectorstore_service()
                count = await vs.add_documents(collection_name, chunks)

                results.append(DocumentUploadResponse(
                    filename=file.filename,
                    collection_name=collection_name,
                    chunks_created=count,
                ))
            finally:
                os.unlink(tmp_path)

        except Exception as e:
            logger.error(f"Error uploading {file.filename}: {e}")
            errors.append(f"{file.filename}: {str(e)}")

    if errors and not results:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    return results


@router.delete("/")
async def delete_document(
    filename: str,
    collection_name: str,
):
    """Delete all chunks of a document from a collection."""
    try:
        vs = get_vectorstore_service()
        await vs.delete_by_metadata(collection_name, "source", filename)
        return {
            "status": "deleted",
            "filename": filename,
            "collection_name": collection_name,
        }
    except Exception as e:
        logger.error(f"Delete document error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

