"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { User, Bot, ChevronDown, FileText, ExternalLink } from "lucide-react";
import { ChatMessage as ChatMessageType, Source } from "@/types";
import { cn } from "@/lib/utils";

interface ChatMessageProps {
  message: ChatMessageType;
}

function SourceCard({ source, index }: { source: Source; index: number }) {
  return (
    <div className="bg-gray-50 border border-jadwa-border rounded-lg p-3 text-sm">
      <div className="flex items-center gap-2 mb-1.5">
        <FileText size={13} className="text-jadwa-tan shrink-0" />
        <span className="font-medium text-jadwa-brown text-xs truncate">
          {source.filename || "Unknown source"}
        </span>
        {source.page && (
          <span className="text-[10px] text-gray-400 shrink-0">p.{source.page}</span>
        )}
        <span className="ml-auto text-[10px] text-gray-400 shrink-0">
          {(source.score * 100).toFixed(0)}% match
        </span>
      </div>
      <p className="text-xs text-gray-600 line-clamp-3 leading-relaxed">
        {source.content}
      </p>
    </div>
  );
}

export default function ChatMessage({ message }: ChatMessageProps) {
  const [showSources, setShowSources] = useState(false);
  const isUser = message.role === "user";
  const hasSources = message.sources && message.sources.length > 0;

  return (
    <div className={cn("animate-fade-in-up flex gap-3", isUser && "flex-row-reverse")}>
      {/* Avatar */}
      <div
        className={cn(
          "w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1",
          isUser ? "bg-jadwa-brown" : "bg-jadwa-tan"
        )}
      >
        {isUser ? (
          <User size={15} className="text-white" />
        ) : (
          <Bot size={15} className="text-jadwa-brown-dark" />
        )}
      </div>

      {/* Message */}
      <div className={cn("max-w-[75%] min-w-0", isUser && "text-right")}>
        <div
          className={cn(
            isUser ? "chat-bubble-user" : "chat-bubble-assistant",
            message.isStreaming && "streaming-cursor"
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose-chat">
              <ReactMarkdown>{message.content}</ReactMarkdown>
            </div>
          )}
        </div>

        {/* Sources toggle */}
        {!isUser && hasSources && !message.isStreaming && (
          <div className="mt-2">
            <button
              onClick={() => setShowSources(!showSources)}
              className="flex items-center gap-1.5 text-xs text-jadwa-slate hover:text-jadwa-brown transition-colors"
            >
              <FileText size={12} />
              {message.sources!.length} source{message.sources!.length > 1 ? "s" : ""}
              <ChevronDown
                size={12}
                className={cn("transition-transform", showSources && "rotate-180")}
              />
            </button>

            {showSources && (
              <div className="mt-2 space-y-2 animate-fade-in-up">
                {message.sources!.map((source, i) => (
                  <SourceCard key={i} source={source} index={i} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

