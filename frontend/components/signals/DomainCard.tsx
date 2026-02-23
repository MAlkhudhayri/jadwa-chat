"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

interface Component {
  name?: string;
  signal?: string | null;
  score?: number;
  value?: number | null;
  unit?: string;
  mom_pct?: number | null;
  yoy_pct?: number | null;
  z_score?: number | null;
  available?: boolean;
}

interface DomainCardProps {
  domain: string;
  label: string;
  score: number;
  direction: string;
  priorScore?: number | null;
  alertCount: number;
  components: Record<string, Component>;
}

const SIGNAL_COLORS: Record<string, string> = {
  strong_up: "bg-green-500 text-white",
  moderate_up: "bg-green-100 text-green-800",
  stable: "bg-yellow-100 text-yellow-800",
  moderate_down: "bg-red-100 text-red-800",
  strong_down: "bg-red-500 text-white",
  reversal_up: "bg-teal-100 text-teal-800",
  reversal_down: "bg-orange-100 text-orange-800",
};

const DIRECTION_ICONS: Record<string, string> = {
  improving: "↑",
  stable: "→",
  deteriorating: "↓",
};

const DIRECTION_COLORS: Record<string, string> = {
  improving: "text-green-600",
  stable: "text-gray-500",
  deteriorating: "text-red-600",
};

function formatSignal(signal: string): string {
  return signal.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatNum(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return v.toFixed(1);
}

export default function DomainCard({
  domain,
  label,
  score,
  direction,
  priorScore,
  alertCount,
  components,
}: DomainCardProps) {
  const [expanded, setExpanded] = useState(false);

  const dirIcon = DIRECTION_ICONS[direction] || "→";
  const dirColor = DIRECTION_COLORS[direction] || "text-gray-500";

  const availableComponents = Object.entries(components).filter(
    ([, c]) => c.available !== false
  );

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden transition-shadow hover:shadow-md">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-gray-900">{label}</span>
          {alertCount > 0 && (
            <span className="px-1.5 py-0.5 text-[10px] font-medium bg-red-100 text-red-700 rounded-full">
              {alertCount} alert{alertCount > 1 ? "s" : ""}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`text-lg font-bold ${
              score > 0 ? "text-green-600" : score < 0 ? "text-red-600" : "text-gray-500"
            }`}
          >
            {score > 0 ? "+" : ""}
            {score.toFixed(1)}
          </span>
          <span className={`text-xs font-medium ${dirColor}`}>
            {direction} {dirIcon}
          </span>
          {expanded ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
        </div>
      </button>

      {/* Expanded Component List */}
      {expanded && (
        <div className="border-t border-gray-100">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-gray-500 text-xs">
                  <th className="text-left px-5 py-2 font-medium">Series</th>
                  <th className="text-center px-3 py-2 font-medium">Signal</th>
                  <th className="text-right px-3 py-2 font-medium">Value</th>
                  <th className="text-right px-3 py-2 font-medium">MoM%</th>
                  <th className="text-right px-3 py-2 font-medium">YoY%</th>
                  <th className="text-right px-5 py-2 font-medium">Z-Score</th>
                </tr>
              </thead>
              <tbody>
                {availableComponents.map(([sid, comp]) => (
                  <tr key={sid} className="border-t border-gray-50 hover:bg-gray-50/50">
                    <td className="px-5 py-2.5 text-gray-800 font-medium">
                      {comp.name || sid.split("__").pop()?.replace(/_/g, " ")}
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      {comp.signal ? (
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                            SIGNAL_COLORS[comp.signal] || "bg-gray-100 text-gray-600"
                          }`}
                        >
                          {formatSignal(comp.signal)}
                        </span>
                      ) : (
                        <span className="text-gray-300">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right text-gray-700 font-mono text-xs">
                      {formatNum(comp.value)} <span className="text-gray-400 text-[10px]">{comp.unit}</span>
                    </td>
                    <td
                      className={`px-3 py-2.5 text-right font-mono text-xs ${
                        (comp.mom_pct ?? 0) > 0
                          ? "text-green-600"
                          : (comp.mom_pct ?? 0) < 0
                          ? "text-red-600"
                          : "text-gray-400"
                      }`}
                    >
                      {comp.mom_pct !== null && comp.mom_pct !== undefined
                        ? `${comp.mom_pct > 0 ? "+" : ""}${comp.mom_pct.toFixed(1)}%`
                        : "—"}
                    </td>
                    <td
                      className={`px-3 py-2.5 text-right font-mono text-xs ${
                        (comp.yoy_pct ?? 0) > 0
                          ? "text-green-600"
                          : (comp.yoy_pct ?? 0) < 0
                          ? "text-red-600"
                          : "text-gray-400"
                      }`}
                    >
                      {comp.yoy_pct !== null && comp.yoy_pct !== undefined
                        ? `${comp.yoy_pct > 0 ? "+" : ""}${comp.yoy_pct.toFixed(1)}%`
                        : "—"}
                    </td>
                    <td className="px-5 py-2.5 text-right font-mono text-xs text-gray-600">
                      {comp.z_score !== null && comp.z_score !== undefined
                        ? `${comp.z_score > 0 ? "+" : ""}${comp.z_score.toFixed(1)}`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}



