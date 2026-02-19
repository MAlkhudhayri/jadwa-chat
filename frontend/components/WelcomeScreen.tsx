"use client";

import Image from "next/image";
import { Database, Upload, MessageSquare, Sparkles } from "lucide-react";

interface WelcomeScreenProps {
  hasCollections: boolean;
  activeCollection: string | null;
  onOpenUpload: () => void;
}

export default function WelcomeScreen({
  hasCollections,
  activeCollection,
  onOpenUpload,
}: WelcomeScreenProps) {
  return (
    <div className="flex-1 flex items-center justify-center p-4 sm:p-8 overflow-y-auto">
      <div className="max-w-lg w-full text-center">
        {/* Logo */}
        <div className="w-12 h-12 sm:w-16 sm:h-16 rounded-[22%] overflow-hidden mx-auto mb-4 sm:mb-6 shadow-lg">
          <Image
            src="/jadwa-logo.png"
            alt="Jadwa Investment"
            width={64}
            height={64}
            className="w-full h-full object-cover"
          />
        </div>

        <h2 className="text-xl sm:text-2xl font-bold text-jadwa-brown mb-2">
          Welcome to JadwaChat
        </h2>
        <p className="text-gray-500 mb-5 sm:mb-8 leading-relaxed text-sm sm:text-base px-2 sm:px-0">
          Your AI powered document assistant. Upload documents to a database and
          start asking questions, JadwaChat will find the answers.
        </p>

        {/* Steps */}
        <div className="grid gap-3 sm:gap-4 text-left">
          <div className="flex items-start gap-3 sm:gap-4 bg-white border border-jadwa-border rounded-xl p-3 sm:p-4">
            <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-lg bg-jadwa-tan/10 flex items-center justify-center shrink-0">
              <Database size={16} className="text-jadwa-tan sm:hidden" />
              <Database size={18} className="text-jadwa-tan hidden sm:block" />
            </div>
            <div>
              <h3 className="font-semibold text-sm text-jadwa-brown mb-0.5">
                1. Create a Database
              </h3>
              <p className="text-xs text-gray-500">
                Use the sidebar to create a new database collection for your documents.
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3 sm:gap-4 bg-white border border-jadwa-border rounded-xl p-3 sm:p-4">
            <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-lg bg-jadwa-tan/10 flex items-center justify-center shrink-0">
              <Upload size={16} className="text-jadwa-tan sm:hidden" />
              <Upload size={18} className="text-jadwa-tan hidden sm:block" />
            </div>
            <div>
              <h3 className="font-semibold text-sm text-jadwa-brown mb-0.5">
                2. Upload Documents
              </h3>
              <p className="text-xs text-gray-500">
                Upload PDFs, Word docs, text files, or CSVs. They&apos;ll be
                automatically processed and indexed.
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3 sm:gap-4 bg-white border border-jadwa-border rounded-xl p-3 sm:p-4">
            <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-lg bg-jadwa-tan/10 flex items-center justify-center shrink-0">
              <MessageSquare size={16} className="text-jadwa-tan sm:hidden" />
              <MessageSquare size={18} className="text-jadwa-tan hidden sm:block" />
            </div>
            <div>
              <h3 className="font-semibold text-sm text-jadwa-brown mb-0.5">
                3. Start Chatting
              </h3>
              <p className="text-xs text-gray-500">
                Ask questions in English or Arabic. JadwaChat retrieves relevant
                passages and generates accurate answers.
              </p>
            </div>
          </div>
        </div>

        {activeCollection && activeCollection !== "all-databases" && (
          <button onClick={onOpenUpload} className="btn-gold mt-6 inline-flex items-center gap-2">
            <Upload size={16} />
            Upload documents to &quot;{activeCollection}&quot;
          </button>
        )}
        {activeCollection === "all-databases" && (
          <p className="mt-6 text-xs text-gray-400">
            Create or select a specific database from the sidebar to upload documents.
          </p>
        )}

        <div className="mt-8 flex items-center justify-center gap-2 text-xs text-gray-400">
          <Sparkles size={12} />
          Powered by Jadwa Investment, Authored by Mohammed Alkhudhayri
        </div>
      </div>
    </div>
  );
}

