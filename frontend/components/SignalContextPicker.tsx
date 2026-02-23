"use client";

import { useEffect, useState, useRef } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpDown,
  ChevronDown,
  Loader2,
  TrendingUp,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

function authHeaders(): Record<string, string> {
  const token =
    typeof window !== "undefined"
      ? localStorage.getItem("jadwachat_token")
      : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface SignalContextItem {
  type: "scorecard" | "anomalies" | "cross_series";
  domain?: string;
  label: string;
}

interface ContextMenuData {
  domains: {
    domain: string;
    label: string;
    score: number;
    direction: string;
    alert_count: number;
  }[];
  aggregate_score: number;
  aggregate_direction: string;
  anomaly_count: number;
  anomaly_critical: number;
  anomaly_warning: number;
  divergence_count: number;
  total_pairs: number;
}

const DIRECTION_ICON: Record<string, string> = {
  improving: "↑",
  stable: "→",
  deteriorating: "↓",
};

interface SignalContextPickerProps {
  selected: SignalContextItem[];
  onChange: (items: SignalContextItem[]) => void;
}

export default function SignalContextPicker({
  selected,
  onChange,
}: SignalContextPickerProps) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ContextMenuData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const fetchMenu = async () => {
    if (data) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/signals/context-menu`, {
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e: any) {
      setError(e.message || "Failed to load signals");
    } finally {
      setLoading(false);
    }
  };

  const handleToggle = () => {
    const next = !open;
    setOpen(next);
    if (next) fetchMenu();
  };

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  const isSelected = (item: SignalContextItem) =>
    selected.some(
      (s) => s.type === item.type && s.domain === item.domain
    );

  const toggle = (item: SignalContextItem) => {
    if (isSelected(item)) {
      onChange(
        selected.filter(
          (s) => !(s.type === item.type && s.domain === item.domain)
        )
      );
    } else {
      onChange([...selected, item]);
    }
  };

  const scoreColor = (score: number) => {
    if (score > 5) return "text-green-600";
    if (score < -5) return "text-red-600";
    return "text-gray-500";
  };

  return (
    <div className="relative" ref={panelRef}>
      {/* Trigger button */}
      <button
        type="button"
        onClick={handleToggle}
        className={cn(
          "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all",
          selected.length > 0
            ? "bg-jadwa-brown/10 text-jadwa-brown border border-jadwa-brown/20"
            : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
        )}
        title="Attach signal engine data as context"
      >
        <Activity size={14} />
        <span className="hidden sm:inline">Signals</span>
        {selected.length > 0 && (
          <span className="bg-jadwa-brown text-white rounded-full w-4 h-4 flex items-center justify-center text-[10px] leading-none">
            {selected.length}
          </span>
        )}
        <ChevronDown
          size={12}
          className={cn("transition-transform", open && "rotate-180")}
        />
      </button>

      {/* Dropdown panel */}
      {open && (
        <div className="absolute bottom-full left-0 mb-2 w-72 bg-white rounded-xl border border-gray-200 shadow-lg z-50 overflow-hidden">
          <div className="px-3 py-2.5 border-b border-gray-100 flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-700">
              Pin Signal Data as Context
            </span>
            {selected.length > 0 && (
              <button
                onClick={() => onChange([])}
                className="text-[10px] text-gray-400 hover:text-red-500 transition-colors"
              >
                Clear all
              </button>
            )}
          </div>

          {loading && (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 text-jadwa-brown animate-spin" />
            </div>
          )}

          {error && (
            <div className="px-3 py-4 text-center">
              <p className="text-xs text-red-500">{error}</p>
              <button
                onClick={() => { setData(null); fetchMenu(); }}
                className="text-xs text-jadwa-brown mt-1 hover:underline"
              >
                Retry
              </button>
            </div>
          )}

          {data && !loading && (
            <div className="max-h-64 overflow-y-auto divide-y divide-gray-50">
              {/* Domain Scorecards */}
              <div className="px-3 py-2">
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  Domain Scorecards
                </p>
                <div className="space-y-1">
                  {data.domains.map((d) => {
                    const item: SignalContextItem = {
                      type: "scorecard",
                      domain: d.domain,
                      label: d.label,
                    };
                    const active = isSelected(item);
                    return (
                      <button
                        key={d.domain}
                        onClick={() => toggle(item)}
                        className={cn(
                          "w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-left transition-all text-xs",
                          active
                            ? "bg-jadwa-brown/10 border border-jadwa-brown/20"
                            : "hover:bg-gray-50 border border-transparent"
                        )}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <TrendingUp
                            size={12}
                            className={active ? "text-jadwa-brown" : "text-gray-400"}
                          />
                          <span
                            className={cn(
                              "truncate",
                              active ? "text-jadwa-brown font-medium" : "text-gray-700"
                            )}
                          >
                            {d.label}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <span className={cn("font-mono text-[11px]", scoreColor(d.score))}>
                            {d.score > 0 ? "+" : ""}
                            {d.score.toFixed(1)}
                          </span>
                          <span className="text-[10px] text-gray-400">
                            {DIRECTION_ICON[d.direction] || "→"}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Anomalies */}
              <div className="px-3 py-2">
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  Anomaly Alerts
                </p>
                {(() => {
                  const item: SignalContextItem = {
                    type: "anomalies",
                    label: `Anomalies (${data.anomaly_count})`,
                  };
                  const active = isSelected(item);
                  return (
                    <button
                      onClick={() => toggle(item)}
                      className={cn(
                        "w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-left transition-all text-xs",
                        active
                          ? "bg-jadwa-brown/10 border border-jadwa-brown/20"
                          : "hover:bg-gray-50 border border-transparent"
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <AlertTriangle
                          size={12}
                          className={active ? "text-jadwa-brown" : "text-orange-400"}
                        />
                        <span
                          className={cn(
                            active ? "text-jadwa-brown font-medium" : "text-gray-700"
                          )}
                        >
                          All Active Anomalies
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0 text-[10px]">
                        {data.anomaly_critical > 0 && (
                          <span className="text-red-500 font-semibold">
                            {data.anomaly_critical} critical
                          </span>
                        )}
                        {data.anomaly_warning > 0 && (
                          <span className="text-orange-500">
                            {data.anomaly_warning} warn
                          </span>
                        )}
                        {data.anomaly_count === 0 && (
                          <span className="text-green-500">None</span>
                        )}
                      </div>
                    </button>
                  );
                })()}
              </div>

              {/* Cross-Series */}
              <div className="px-3 py-2">
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  Cross-Series Analysis
                </p>
                {(() => {
                  const item: SignalContextItem = {
                    type: "cross_series",
                    label: `Divergences (${data.divergence_count})`,
                  };
                  const active = isSelected(item);
                  return (
                    <button
                      onClick={() => toggle(item)}
                      className={cn(
                        "w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-left transition-all text-xs",
                        active
                          ? "bg-jadwa-brown/10 border border-jadwa-brown/20"
                          : "hover:bg-gray-50 border border-transparent"
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <ArrowUpDown
                          size={12}
                          className={active ? "text-jadwa-brown" : "text-gray-400"}
                        />
                        <span
                          className={cn(
                            active ? "text-jadwa-brown font-medium" : "text-gray-700"
                          )}
                        >
                          Cross-Series Divergences
                        </span>
                      </div>
                      <span className="text-[10px] text-gray-400 shrink-0">
                        {data.total_pairs} pairs monitored
                      </span>
                    </button>
                  );
                })()}
              </div>
            </div>
          )}

          <div className="px-3 py-2 border-t border-gray-100 bg-gray-50/50">
            <p className="text-[10px] text-gray-400 text-center">
              Selected items are injected as context in your next message
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
