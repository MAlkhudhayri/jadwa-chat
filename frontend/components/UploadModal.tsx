"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import {
  X,
  Upload,
  FileText,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Database,
  FileSearch,
} from "lucide-react";
import { uploadDocument, uploadTimeSeriesFile } from "@/lib/api";
import { UploadResponse } from "@/types";

interface UploadModalProps {
  collectionName: string;
  isOpen: boolean;
  onClose: () => void;
  onUploadComplete: () => void;
}

const TIMESERIES_EXTS = [".csv", ".xlsx", ".xls"];

function getFileType(filename: string): "timeseries" | "document" {
  const ext = filename.slice(filename.lastIndexOf(".")).toLowerCase();
  return TIMESERIES_EXTS.includes(ext) ? "timeseries" : "document";
}

interface FileUploadState {
  file: File;
  fileType: "timeseries" | "document";
  status: "pending" | "uploading" | "success" | "error";
  result?: any;
  error?: string;
}

export default function UploadModal({
  collectionName,
  isOpen,
  onClose,
  onUploadComplete,
}: UploadModalProps) {
  const [files, setFiles] = useState<FileUploadState[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newFiles = acceptedFiles.map((file) => ({
      file,
      fileType: getFileType(file.name) as "timeseries" | "document",
      status: "pending" as const,
    }));
    setFiles((prev) => [...prev, ...newFiles]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "text/csv": [".csv"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "text/plain": [".txt"],
      "text/markdown": [".md"],
    },
    maxSize: 50 * 1024 * 1024,
  });

  const handleUpload = async () => {
    setIsUploading(true);

    for (let i = 0; i < files.length; i++) {
      if (files[i].status !== "pending") continue;

      setFiles((prev) =>
        prev.map((f, idx) =>
          idx === i ? { ...f, status: "uploading" as const } : f
        )
      );

      try {
        let result;
        if (files[i].fileType === "timeseries") {
          // CSV/Excel → SQLite time series
          result = await uploadTimeSeriesFile(files[i].file);
        } else {
          // PDF/DOCX/TXT/MD → Qdrant document embeddings
          result = await uploadDocument(files[i].file, collectionName);
        }
        setFiles((prev) =>
          prev.map((f, idx) =>
            idx === i ? { ...f, status: "success" as const, result } : f
          )
        );
      } catch (err: any) {
        setFiles((prev) =>
          prev.map((f, idx) =>
            idx === i
              ? { ...f, status: "error" as const, error: err.message }
              : f
          )
        );
      }
    }

    setIsUploading(false);
    onUploadComplete();
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleClose = () => {
    setFiles([]);
    onClose();
  };

  if (!isOpen) return null;

  const pendingCount = files.filter((f) => f.status === "pending").length;
  const successCount = files.filter((f) => f.status === "success").length;
  const tsCount = files.filter((f) => f.fileType === "timeseries").length;
  const docCount = files.filter((f) => f.fileType === "document").length;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-jadwa-border">
          <div>
            <h2 className="font-semibold text-jadwa-navy">Upload Data</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              CSV/Excel → Time Series &nbsp;|&nbsp; PDF/DOCX → Document Search
            </p>
          </div>
          <button onClick={handleClose} className="text-gray-400 hover:text-gray-600">
            <X size={20} />
          </button>
        </div>

        {/* Dropzone */}
        <div className="p-5">
          <div
            {...getRootProps()}
            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
              isDragActive
                ? "dropzone-active border-jadwa-gold"
                : "border-gray-300 hover:border-jadwa-navy/30"
            }`}
          >
            <input {...getInputProps()} />
            <Upload
              size={32}
              className={`mx-auto mb-3 ${
                isDragActive ? "text-jadwa-gold" : "text-gray-400"
              }`}
            />
            <p className="text-sm text-gray-600 font-medium">
              {isDragActive
                ? "Drop files here..."
                : "Drag & drop files, or click to browse"}
            </p>
            <div className="flex justify-center gap-4 mt-3">
              <div className="flex items-center gap-1.5 text-[11px] text-gray-400">
                <Database size={12} className="text-jadwa-gold" />
                CSV, Excel → Time Series
              </div>
              <div className="flex items-center gap-1.5 text-[11px] text-gray-400">
                <FileSearch size={12} className="text-jadwa-navy" />
                PDF, DOCX, TXT → Documents
              </div>
            </div>
          </div>
        </div>

        {/* File list */}
        {files.length > 0 && (
          <div className="px-5 pb-3 max-h-48 overflow-y-auto">
            <div className="space-y-2">
              {files.map((f, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 bg-gray-50 rounded-lg px-3 py-2.5"
                >
                  {f.fileType === "timeseries" ? (
                    <Database size={16} className="text-jadwa-gold shrink-0" />
                  ) : (
                    <FileText size={16} className="text-jadwa-navy shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm truncate">{f.file.name}</p>
                    <p className="text-[10px] text-gray-400">
                      {(f.file.size / 1024).toFixed(0)} KB
                      <span className={`ml-1.5 px-1 py-0.5 rounded text-[9px] font-medium ${
                        f.fileType === "timeseries"
                          ? "bg-jadwa-gold/10 text-jadwa-gold-dark"
                          : "bg-jadwa-navy/10 text-jadwa-navy"
                      }`}>
                        {f.fileType === "timeseries" ? "→ SQLite" : "→ Qdrant"}
                      </span>
                      {f.result?.rows_inserted !== undefined &&
                        ` · ${f.result.rows_inserted} rows`}
                      {f.result?.chunks_created !== undefined &&
                        ` · ${f.result.chunks_created} chunks`}
                    </p>
                  </div>
                  {f.status === "pending" && (
                    <button
                      onClick={() => removeFile(i)}
                      className="text-gray-400 hover:text-red-400"
                    >
                      <X size={14} />
                    </button>
                  )}
                  {f.status === "uploading" && (
                    <Loader2 size={16} className="text-jadwa-gold animate-spin" />
                  )}
                  {f.status === "success" && (
                    <CheckCircle2 size={16} className="text-green-500" />
                  )}
                  {f.status === "error" && (
                    <div className="flex items-center gap-1">
                      <AlertCircle size={14} className="text-red-500" />
                      <span className="text-[10px] text-red-500 max-w-[100px] truncate">
                        {f.error}
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="p-5 border-t border-jadwa-border flex items-center justify-between">
          <p className="text-xs text-gray-400">
            {files.length} file{files.length !== 1 ? "s" : ""}
            {tsCount > 0 && ` · ${tsCount} data`}
            {docCount > 0 && ` · ${docCount} doc`}
            {successCount > 0 && ` · ${successCount} uploaded`}
          </p>
          <div className="flex gap-2">
            <button onClick={handleClose} className="btn-ghost text-sm">
              {successCount > 0 ? "Done" : "Cancel"}
            </button>
            {pendingCount > 0 && (
              <button
                onClick={handleUpload}
                disabled={isUploading}
                className="btn-primary text-sm flex items-center gap-2"
              >
                {isUploading ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Processing...
                  </>
                ) : (
                  <>
                    <Upload size={14} />
                    Upload {pendingCount} file{pendingCount !== 1 ? "s" : ""}
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
