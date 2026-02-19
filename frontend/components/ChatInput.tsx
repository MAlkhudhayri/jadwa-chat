"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled: boolean;
  placeholder?: string;
}

export default function ChatInput({ onSend, disabled, placeholder }: ChatInputProps) {
  const [message, setMessage] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const adjustHeight = () => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  };

  useEffect(() => {
    adjustHeight();
  }, [message]);

  const handleSubmit = () => {
    const trimmed = message.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setMessage("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="border-t border-jadwa-border bg-white px-2 sm:px-4 py-2 sm:py-3">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-end gap-2 sm:gap-3 bg-jadwa-surface border border-jadwa-border rounded-xl px-3 sm:px-4 py-2.5 sm:py-3 focus-within:ring-2 focus-within:ring-jadwa-brown/15 focus-within:border-jadwa-brown/30 transition-all">
          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder || "Ask JadwaChat anything..."}
            disabled={disabled}
            rows={1}
            className="flex-1 bg-transparent resize-none focus:outline-none text-sm placeholder:text-gray-400 min-h-[24px] max-h-[120px] sm:max-h-[200px] leading-relaxed disabled:opacity-50"
          />
          <button
            onClick={handleSubmit}
            disabled={disabled || !message.trim()}
            className={cn(
              "shrink-0 w-9 h-9 rounded-lg flex items-center justify-center transition-all duration-200",
              message.trim() && !disabled
                ? "bg-jadwa-brown text-white hover:bg-jadwa-brown-light active:scale-95"
                : "bg-gray-200 text-gray-400 cursor-not-allowed"
            )}
          >
            {disabled ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Send size={16} />
            )}
          </button>
        </div>
        <p className="text-[10px] text-gray-400 text-center mt-1.5 sm:mt-2 hidden sm:block">
          JadwaChat can make mistakes. Verify important information from source documents.
        </p>
      </div>
    </div>
  );
}

