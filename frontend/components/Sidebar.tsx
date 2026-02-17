"use client";

import { useState } from "react";
import {
  MessageSquarePlus,
  Database,
  MessageCircle,
  Trash2,
  Plus,
  ChevronDown,
  Upload,
  X,
  FolderOpen,
} from "lucide-react";
import { Collection, Conversation } from "@/types";
import { cn, formatDate, truncate } from "@/lib/utils";

interface SidebarProps {
  collections: Collection[];
  conversations: Conversation[];
  activeCollection: string | null;
  activeConversation: string | null;
  onSelectCollection: (name: string) => void;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  onDeleteConversation: (id: string) => void;
  onCreateCollection: (name: string, description?: string) => void;
  onDeleteCollection: (name: string) => void;
  onOpenUpload: () => void;
  isOpen: boolean;
  onToggle: () => void;
}

export default function Sidebar({
  collections,
  conversations,
  activeCollection,
  activeConversation,
  onSelectCollection,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  onCreateCollection,
  onDeleteCollection,
  onOpenUpload,
  isOpen,
  onToggle,
}: SidebarProps) {
  const [showNewCollection, setShowNewCollection] = useState(false);
  const [newColName, setNewColName] = useState("");
  const [newColDesc, setNewColDesc] = useState("");
  const [collectionExpanded, setCollectionExpanded] = useState(true);

  const handleCreateCollection = () => {
    if (!newColName.trim()) return;
    onCreateCollection(newColName.trim(), newColDesc.trim() || undefined);
    setNewColName("");
    setNewColDesc("");
    setShowNewCollection(false);
  };

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={onToggle}
        />
      )}

      <aside
        className={cn(
          "fixed lg:relative z-50 h-full bg-jadwa-navy-dark text-white flex flex-col",
          "transition-all duration-300 ease-in-out",
          isOpen ? "w-72 translate-x-0" : "w-0 -translate-x-full lg:w-0"
        )}
      >
        <div className="flex flex-col h-full w-72 overflow-hidden">
          {/* Header */}
          <div className="p-4 border-b border-white/10">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-jadwa-gold flex items-center justify-center">
                  <span className="text-jadwa-navy-dark font-bold text-sm">J</span>
                </div>
                <div>
                  <h1 className="font-semibold text-sm">JadwaChat</h1>
                  <p className="text-[10px] text-white/50">AI Document Assistant</p>
                </div>
              </div>
              <button onClick={onToggle} className="lg:hidden text-white/60 hover:text-white">
                <X size={18} />
              </button>
            </div>

            <button
              onClick={onNewConversation}
              className="w-full flex items-center gap-2 btn-gold text-sm py-2.5 justify-center"
            >
              <MessageSquarePlus size={16} />
              New Chat
            </button>
          </div>

          {/* Collections */}
          <div className="px-3 pt-3">
            <button
              onClick={() => setCollectionExpanded(!collectionExpanded)}
              className="flex items-center justify-between w-full text-xs font-semibold text-white/40 uppercase tracking-wider px-1 mb-2"
            >
              <span className="flex items-center gap-1.5">
                <Database size={12} />
                Databases
              </span>
              <ChevronDown
                size={14}
                className={cn("transition-transform", !collectionExpanded && "-rotate-90")}
              />
            </button>

            {collectionExpanded && (
              <div className="space-y-0.5 mb-2">
                {collections.map((col) => (
                  <div
                    key={col.name}
                    className={cn(
                      "group flex items-center justify-between px-2.5 py-2 rounded-lg text-sm cursor-pointer transition-colors",
                      activeCollection === col.name
                        ? "bg-white/15 text-white"
                        : "text-white/70 hover:bg-white/8 hover:text-white"
                    )}
                    onClick={() => onSelectCollection(col.name)}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <FolderOpen size={14} className="shrink-0 text-jadwa-gold" />
                      <span className="truncate">{col.name}</span>
                      <span className="text-[10px] text-white/30 shrink-0">
                        {col.document_count}
                      </span>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteCollection(col.name);
                      }}
                      className="hidden group-hover:block text-white/30 hover:text-red-400 transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}

                {!showNewCollection ? (
                  <button
                    onClick={() => setShowNewCollection(true)}
                    className="flex items-center gap-2 px-2.5 py-2 text-sm text-white/40 hover:text-white/70 transition-colors w-full"
                  >
                    <Plus size={14} />
                    Add database
                  </button>
                ) : (
                  <div className="px-2 py-2 space-y-2">
                    <input
                      value={newColName}
                      onChange={(e) => setNewColName(e.target.value.replace(/[^a-zA-Z0-9_-]/g, ""))}
                      placeholder="collection-name"
                      className="w-full bg-white/10 text-white text-sm rounded px-2.5 py-1.5 placeholder:text-white/30 focus:outline-none focus:ring-1 focus:ring-jadwa-gold"
                      autoFocus
                      onKeyDown={(e) => e.key === "Enter" && handleCreateCollection()}
                    />
                    <input
                      value={newColDesc}
                      onChange={(e) => setNewColDesc(e.target.value)}
                      placeholder="Description (optional)"
                      className="w-full bg-white/10 text-white text-sm rounded px-2.5 py-1.5 placeholder:text-white/30 focus:outline-none focus:ring-1 focus:ring-jadwa-gold"
                    />
                    <div className="flex gap-1.5">
                      <button
                        onClick={handleCreateCollection}
                        className="flex-1 text-xs bg-jadwa-gold text-jadwa-navy-dark py-1.5 rounded font-medium"
                      >
                        Create
                      </button>
                      <button
                        onClick={() => setShowNewCollection(false)}
                        className="flex-1 text-xs text-white/50 hover:text-white py-1.5 rounded"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}

                {activeCollection && (
                  <button
                    onClick={onOpenUpload}
                    className="flex items-center gap-2 px-2.5 py-2 text-sm text-jadwa-gold/80 hover:text-jadwa-gold transition-colors w-full"
                  >
                    <Upload size={14} />
                    Upload documents
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Conversations */}
          <div className="flex-1 overflow-y-auto px-3 pt-2">
            <div className="text-xs font-semibold text-white/40 uppercase tracking-wider px-1 mb-2 flex items-center gap-1.5">
              <MessageCircle size={12} />
              Conversations
            </div>

            <div className="space-y-0.5">
              {conversations.length === 0 ? (
                <p className="text-xs text-white/30 px-2 py-4 text-center">
                  No conversations yet.
                  {!activeCollection && <br />}
                  {!activeCollection && "Select a database to start."}
                </p>
              ) : (
                conversations.map((conv) => (
                  <div
                    key={conv.conversation_id}
                    className={cn(
                      "group flex items-center justify-between px-2.5 py-2 rounded-lg text-sm cursor-pointer transition-colors",
                      activeConversation === conv.conversation_id
                        ? "bg-white/15 text-white"
                        : "text-white/70 hover:bg-white/8 hover:text-white"
                    )}
                    onClick={() => onSelectConversation(conv.conversation_id)}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm">{truncate(conv.title, 30)}</p>
                      <p className="text-[10px] text-white/30 mt-0.5">
                        {formatDate(conv.updated_at)}
                      </p>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteConversation(conv.conversation_id);
                      }}
                      className="hidden group-hover:block text-white/30 hover:text-red-400 transition-colors ml-2"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Footer */}
          <div className="p-3 border-t border-white/10">
            <p className="text-[10px] text-white/25 text-center">
              Powered by RAG · Qdrant · GPT-4o
            </p>
          </div>
        </div>
      </aside>
    </>
  );
}

