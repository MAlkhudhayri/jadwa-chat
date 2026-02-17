"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Menu, Database, AlertTriangle, Layers } from "lucide-react";

const ALL_DATABASES_KEY = "all-databases";
import Sidebar from "@/components/Sidebar";
import ChatMessage from "@/components/ChatMessage";
import ChatInput from "@/components/ChatInput";
import UploadModal from "@/components/UploadModal";
import WelcomeScreen from "@/components/WelcomeScreen";
import {
  fetchCollections,
  fetchConversations,
  fetchConversation,
  createCollection,
  deleteCollection,
  deleteConversation,
  askQuestion,
} from "@/lib/api";
import { ChatMessage as ChatMessageType, Collection, Conversation } from "@/types";

export default function Home() {
  // State
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeCollection, setActiveCollection] = useState<string | null>(null);
  const [activeConversation, setActiveConversation] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Load collections on mount
  useEffect(() => {
    loadCollections();
  }, []);

  // Load conversations when collection changes
  useEffect(() => {
    if (activeCollection) {
      loadConversations(activeCollection);
    } else {
      setConversations([]);
    }
  }, [activeCollection]);

  // ─── Data Loading ───────────────────────────────────

  const loadCollections = async () => {
    try {
      const cols = await fetchCollections();
      setCollections(cols);
      setError(null);
    } catch (err: any) {
      console.error("Failed to load collections:", err);
      setError("Cannot connect to backend. Make sure the server is running.");
    }
  };

  const loadConversations = async (collectionName: string) => {
    try {
      const convs = await fetchConversations(collectionName);
      setConversations(convs);
    } catch (err) {
      console.error("Failed to load conversations:", err);
    }
  };

  const loadConversation = async (conversationId: string) => {
    try {
      const data = await fetchConversation(conversationId);
      setMessages(
        data.messages.map((m: any) => ({
          role: m.role,
          content: m.content,
          sources: m.sources,
        }))
      );
    } catch (err) {
      console.error("Failed to load conversation:", err);
    }
  };

  // ─── Actions ────────────────────────────────────────

  const handleSelectCollection = (name: string) => {
    setActiveCollection(name);
    setActiveConversation(null);
    setMessages([]);
  };

  const handleSelectConversation = (id: string) => {
    setActiveConversation(id);
    loadConversation(id);
  };

  const handleNewConversation = () => {
    setActiveConversation(null);
    setMessages([]);
  };

  const handleDeleteConversation = async (id: string) => {
    try {
      await deleteConversation(id);
      if (activeConversation === id) {
        setActiveConversation(null);
        setMessages([]);
      }
      if (activeCollection) loadConversations(activeCollection);
    } catch (err) {
      console.error("Failed to delete conversation:", err);
    }
  };

  const handleCreateCollection = async (name: string, description?: string) => {
    try {
      await createCollection(name, description);
      await loadCollections();
      setActiveCollection(name);
    } catch (err) {
      console.error("Failed to create collection:", err);
    }
  };

  const handleDeleteCollection = async (name: string) => {
    if (!confirm(`Delete database "${name}" and all its documents?`)) return;
    try {
      await deleteCollection(name);
      if (activeCollection === name) {
        setActiveCollection(null);
        setActiveConversation(null);
        setMessages([]);
      }
      await loadCollections();
    } catch (err) {
      console.error("Failed to delete collection:", err);
    }
  };

  const handleUploadComplete = () => {
    loadCollections();
  };

  // ─── Chat ──────────────────────────────────────────

  const handleSendMessage = async (message: string) => {
    if (!activeCollection || isStreaming) return;

    // Add user message
    const userMsg: ChatMessageType = { role: "user", content: message };
    setMessages((prev) => [...prev, userMsg]);

    // Add placeholder assistant message
    const assistantMsg: ChatMessageType = {
      role: "assistant",
      content: "",
      isStreaming: true,
    };
    setMessages((prev) => [...prev, assistantMsg]);
    setIsStreaming(true);
    setError(null);

    try {
      // Use orchestrator — routes data queries to SQLite, document queries to Qdrant
      const result = await askQuestion(
        message,
        activeCollection,
        activeConversation || undefined
      );

      // Update assistant message with full response
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last.role === "assistant") {
          // Append citations to the answer if present
          let fullAnswer = result.answer;
          if (result.citations) {
            fullAnswer += "\n\nCitations:\n" + result.citations;
          }
          last.content = fullAnswer;
          last.sources = result.sources;
          last.isStreaming = false;
        }
        return updated;
      });

      // Track conversation
      if (result.conversation_id) {
        setActiveConversation(result.conversation_id);
      }

      // Reload conversations
      if (activeCollection) loadConversations(activeCollection);
    } catch (err: any) {
      console.error("Chat error:", err);
      setError(err.message || "Failed to send message");
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last.role === "assistant" && last.isStreaming) {
          last.content = "Sorry, an error occurred. Please try again.";
          last.isStreaming = false;
        }
        return updated;
      });
    } finally {
      setIsStreaming(false);
    }
  };

  // ─── Render ─────────────────────────────────────────

  const showWelcome = messages.length === 0;

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <Sidebar
        collections={collections}
        conversations={conversations}
        activeCollection={activeCollection}
        activeConversation={activeConversation}
        onSelectCollection={handleSelectCollection}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onDeleteConversation={handleDeleteConversation}
        onCreateCollection={handleCreateCollection}
        onDeleteCollection={handleDeleteCollection}
        onOpenUpload={() => setUploadOpen(true)}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
      />

      {/* Main Content */}
      <main className="flex-1 flex flex-col min-w-0 h-full">
        {/* Top Bar */}
        <header className="h-14 border-b border-jadwa-border bg-white flex items-center px-4 shrink-0">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="btn-ghost p-2 mr-2"
          >
            <Menu size={18} />
          </button>

          {activeCollection ? (
            <div className="flex items-center gap-2">
              {activeCollection === ALL_DATABASES_KEY ? (
                <Layers size={16} className="text-jadwa-gold" />
              ) : (
                <Database size={16} className="text-jadwa-gold" />
              )}
              <span className="font-medium text-sm text-jadwa-navy">
                {activeCollection === ALL_DATABASES_KEY ? "All Databases" : activeCollection}
              </span>
              <span className="text-xs text-gray-400">
                {collections.find((c) => c.name === activeCollection)?.document_count || 0}{" "}
                items
              </span>
              {activeCollection === ALL_DATABASES_KEY && (
                <span className="text-[10px] bg-jadwa-gold/10 text-jadwa-gold-dark px-1.5 py-0.5 rounded font-medium">
                  Cross-DB
                </span>
              )}
            </div>
          ) : (
            <span className="text-sm text-gray-400">
              Select a database to start chatting
            </span>
          )}
        </header>

        {/* Error Banner */}
        {error && (
          <div className="bg-red-50 border-b border-red-200 px-4 py-2.5 flex items-center gap-2 text-sm text-red-700">
            <AlertTriangle size={15} />
            {error}
            <button
              onClick={() => setError(null)}
              className="ml-auto text-red-400 hover:text-red-600"
            >
              ✕
            </button>
          </div>
        )}

        {/* Chat Area */}
        {showWelcome ? (
          <WelcomeScreen
            hasCollections={collections.length > 0}
            activeCollection={activeCollection}
            onOpenUpload={() => setUploadOpen(true)}
          />
        ) : (
          <div
            ref={chatContainerRef}
            className="flex-1 overflow-y-auto px-4 py-6"
          >
            <div className="max-w-3xl mx-auto space-y-6">
              {messages.map((msg, i) => (
                <ChatMessage key={i} message={msg} />
              ))}
              <div ref={messagesEndRef} />
            </div>
          </div>
        )}

        {/* Input */}
        {/* Empty collection warning */}
        {activeCollection &&
          collections.find((c) => c.name === activeCollection)?.document_count === 0 &&
          messages.length === 0 && (
            <div className="bg-amber-50 border-t border-amber-200 px-4 py-3 flex items-center gap-2 text-sm text-amber-700">
              <AlertTriangle size={15} />
              <span>
                This database has no documents yet.{" "}
                <button
                  onClick={() => setUploadOpen(true)}
                  className="underline font-medium hover:text-amber-900"
                >
                  Upload documents
                </button>{" "}
                to start chatting.
              </span>
            </div>
          )}

        <ChatInput
          onSend={handleSendMessage}
          disabled={!activeCollection || isStreaming}
          placeholder={
            !activeCollection
              ? "Select a database from the sidebar to start chatting..."
              : isStreaming
              ? "JadwaChat is thinking..."
              : activeCollection === ALL_DATABASES_KEY
              ? "Ask across all databases..."
              : `Ask about "${activeCollection}"...`
          }
        />
      </main>

      {/* Upload Modal — not available on "All Databases" */}
      {activeCollection && activeCollection !== ALL_DATABASES_KEY && (
        <UploadModal
          collectionName={activeCollection}
          isOpen={uploadOpen}
          onClose={() => setUploadOpen(false)}
          onUploadComplete={handleUploadComplete}
        />
      )}
    </div>
  );
}

