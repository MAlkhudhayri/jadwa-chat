"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  ArrowUpDown,
  CheckCircle2,
  ChevronRight,
  Cpu,
  FileText,
  Loader2,
  Maximize2,
  Play,
  RefreshCw,
  TrendingUp,
  X,
  XCircle,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import ScoreGauge from "@/components/signals/ScoreGauge";
import AgentDebate from "@/components/signals/AgentDebate";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

function authHeaders(): Record<string, string> {
  const token =
    typeof window !== "undefined"
      ? localStorage.getItem("jadwachat_token")
      : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function jsonAuthHeaders(): Record<string, string> {
  return { "Content-Type": "application/json", ...authHeaders() };
}

interface DashboardData {
  report_date: string | null;
  aggregate_score: number;
  aggregate_direction: string;
  scorecards: any[];
  anomalies: any[];
  anomaly_count: number;
  cross_series_alerts: any[];
  divergence_count: number;
  last_run: {
    finished_at: string | null;
    series_processed: number;
    duration_ms: number | null;
  };
  series_count: number;
}

interface ModelInfo {
  name: string;
  description: string;
  category: string;
  status: string;
  loaded_at: string | null;
  last_run_at: string | null;
  last_run_ms: number | null;
  size_mb: number | null;
  error: string | null;
  meta: Record<string, any>;
}

interface ModelsStatusData {
  total: number;
  ready: number;
  models: ModelInfo[];
}

const DIRECTION_ICON: Record<string, string> = {
  improving: "^",
  stable: "->",
  deteriorating: "v",
};

const SEVERITY_DOT: Record<string, string> = {
  critical: "bg-red-500",
  warning: "bg-orange-500",
  watch: "bg-blue-500",
};

const CATEGORY_COLORS: Record<string, { bg: string; text: string }> = {
  rag: { bg: "bg-blue-100", text: "text-blue-700" },
  anomaly: { bg: "bg-red-100", text: "text-red-700" },
  forecast: { bg: "bg-purple-100", text: "text-purple-700" },
  attribution: { bg: "bg-amber-100", text: "text-amber-700" },
  clustering: { bg: "bg-teal-100", text: "text-teal-700" },
};

const STATUS_CONFIG: Record<string, { icon: any; color: string; label: string }> = {
  ready: { icon: CheckCircle2, color: "text-green-600", label: "Ready" },
  loading: { icon: Loader2, color: "text-amber-500", label: "Loading" },
  error: { icon: XCircle, color: "text-red-500", label: "Error" },
  not_loaded: { icon: Cpu, color: "text-gray-400", label: "Not Loaded" },
};

interface SignalPanelProps {
  isOpen: boolean;
  onToggle: () => void;
}

type Tab = "overview" | "anomalies" | "debate" | "models";

export default function SignalPanel({ isOpen, onToggle }: SignalPanelProps) {
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");

  const [modelsData, setModelsData] = useState<ModelsStatusData | null>(null);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [computeLoading, setComputeLoading] = useState(false);
  const [computeResult, setComputeResult] = useState<any>(null);

  // IC Memo Autopilot state
  const [memoTopic, setMemoTopic] = useState("");
  const [memoLoading, setMemoLoading] = useState(false);
  const [memoResult, setMemoResult] = useState<string | null>(null);
  const [memoError, setMemoError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && !data && !loading) {
      fetchDashboard();
    }
  }, [isOpen]);

  useEffect(() => {
    if (isOpen && tab === "models" && !modelsData && !modelsLoading) {
      fetchModelsStatus();
    }
  }, [isOpen, tab]);

  const fetchDashboard = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/signals/dashboard`, { headers: authHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e: any) {
      setError(e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  const fetchModelsStatus = async () => {
    setModelsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/signals/models/status`, { headers: authHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setModelsData(await res.json());
    } catch {
      // silently fail
    } finally {
      setModelsLoading(false);
    }
  };

  const warmModel = async (modelName?: string) => {
    try {
      const res = await fetch(`${API_BASE}/signals/models/warm`, {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify(modelName ? { model: modelName } : {}),
      });
      if (res.ok) await fetchModelsStatus();
    } catch { /* ignore */ }
  };

  const runCompute = async () => {
    setComputeLoading(true);
    setComputeResult(null);
    try {
      const res = await fetch(`${API_BASE}/signals/models/compute`, {
        method: "POST",
        headers: jsonAuthHeaders(),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setComputeResult(await res.json());
      await fetchModelsStatus();
    } catch { /* ignore */ }
    finally { setComputeLoading(false); }
  };

  const generateMemo = async (topic?: string) => {
    const t = (topic || memoTopic).trim();
    if (!t) return;
    setMemoLoading(true);
    setMemoResult(null);
    setMemoError(null);
    try {
      const res = await fetch(`${API_BASE}/signals/memo`, {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({ topic: t }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setMemoResult(data.memo);
    } catch (e: any) {
      setMemoError(e.message || "Failed to generate memo");
    } finally {
      setMemoLoading(false);
    }
  };

  const scorecards = data?.scorecards || [];
  const anomalies = data?.anomalies || [];

  // ── Collapsed state: narrow teal vertical bar ───────────────────────
  if (!isOpen) {
    return (
      <div
        className="hidden lg:flex w-[52px] h-full bg-teal-700 flex-col items-center pt-4 pb-3 cursor-pointer hover:bg-teal-600 transition-colors shrink-0 border-l border-teal-800"
        onClick={onToggle}
        title="Expand Signal Engine"
      >
        <div className="w-9 h-9 rounded-xl bg-white/15 flex items-center justify-center mb-2">
          <Activity size={18} className="text-white" />
        </div>
        <div className="flex flex-col items-center gap-0.5 mt-1">
          <span
            className="text-[9px] font-bold text-white/90 tracking-widest uppercase"
            style={{ writingMode: "vertical-rl", textOrientation: "mixed" }}
          >
            Signal Engine
          </span>
        </div>

        {/* Status dots at the bottom */}
        <div className="mt-auto flex flex-col items-center gap-2 pb-2">
          {data && (
            <>
              <div className="flex flex-col items-center gap-1" title={`Score: ${data.aggregate_score}`}>
                <span className={`text-[10px] font-bold font-mono ${data.aggregate_score > 0 ? "text-green-300" : data.aggregate_score < 0 ? "text-red-300" : "text-white/60"}`}>
                  {data.aggregate_score > 0 ? "+" : ""}{data.aggregate_score.toFixed(0)}
                </span>
              </div>
              {data.anomaly_count > 0 && (
                <div
                  className="w-6 h-6 rounded-full bg-red-500/20 flex items-center justify-center"
                  title={`${data.anomaly_count} anomalies`}
                >
                  <span className="text-[9px] font-bold text-red-300">{data.anomaly_count}</span>
                </div>
              )}
            </>
          )}
          {modelsData && (
            <div
              className="w-6 h-6 rounded-full bg-white/10 flex items-center justify-center"
              title={`${modelsData.ready}/${modelsData.total} models ready`}
            >
              <span className="text-[9px] font-bold text-white/70">
                {modelsData.ready}/{modelsData.total}
              </span>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Expanded state: full panel ──────────────────────────────────────
  return (
    <div className="w-[380px] lg:w-[420px] h-full border-l border-teal-800 bg-gray-50 flex flex-col shrink-0 overflow-hidden">
      {/* Header */}
      <div className="h-12 sm:h-14 bg-teal-700 flex items-center justify-between px-3 shrink-0">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-white/80" />
          <span className="text-sm font-semibold text-white">Signal Engine</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => router.push("/signals")}
            className="p-1.5 hover:bg-white/10 rounded-lg transition-colors"
            title="Expand to full page"
          >
            <Maximize2 size={14} className="text-white/70" />
          </button>
          <button
            onClick={onToggle}
            className="p-1.5 hover:bg-white/10 rounded-lg transition-colors"
            title="Collapse panel"
          >
            <X size={14} className="text-white/70" />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex bg-teal-50 px-1 shrink-0 border-b border-teal-700/10">
        {(
          [
            { id: "overview" as Tab, label: "Overview" },
            { id: "anomalies" as Tab, label: `Alerts${data ? ` (${data.anomaly_count})` : ""}` },
            { id: "debate" as Tab, label: "Debate" },
            { id: "models" as Tab, label: `Models${modelsData ? ` (${modelsData.ready}/${modelsData.total})` : ""}` },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 py-2.5 text-[11px] font-semibold transition-colors ${
              tab === t.id
                ? "text-teal-700 border-b-2 border-teal-700 bg-white/60"
                : "text-teal-700/40 hover:text-teal-700/70"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="w-6 h-6 text-teal-700 animate-spin" />
          </div>
        )}

        {error && !data && (
          <div className="p-4 text-center">
            <AlertTriangle className="w-8 h-8 text-orange-400 mx-auto mb-2" />
            <p className="text-xs text-gray-500 mb-2">{error}</p>
            <button onClick={fetchDashboard} className="text-xs text-teal-700 font-medium hover:underline">
              Retry
            </button>
          </div>
        )}

        {data && tab === "overview" && (
          <div className="p-3 space-y-3">
            {/* IC Memo Autopilot */}
            <div className="bg-gradient-to-br from-teal-700 to-teal-800 rounded-xl px-4 py-3.5 text-white">
              <div className="flex items-center gap-2 mb-2">
                <FileText size={14} className="text-teal-200" />
                <span className="text-[11px] font-bold uppercase tracking-wider text-teal-100">IC Memo Autopilot</span>
              </div>
              {!memoResult ? (
                <>
                  <div className="flex gap-2 mb-2">
                    <input
                      type="text"
                      value={memoTopic}
                      onChange={(e) => setMemoTopic(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") generateMemo(); }}
                      placeholder="e.g. Saudi banking liquidity..."
                      className="flex-1 px-3 py-2 text-[11px] bg-white/10 border border-white/20 rounded-lg text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-white/30"
                      disabled={memoLoading}
                    />
                    <button
                      onClick={() => generateMemo()}
                      disabled={!memoTopic.trim() || memoLoading}
                      className="px-3 py-2 bg-white/20 rounded-lg text-[11px] font-semibold hover:bg-white/30 transition-colors disabled:opacity-40 whitespace-nowrap"
                    >
                      {memoLoading ? <Loader2 size={14} className="animate-spin" /> : "Generate"}
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {[
                      "Saudi banking liquidity",
                      "Oil downside scenario",
                      "Inflation persistence risk",
                      "Monetary policy outlook",
                    ].map((t) => (
                      <button
                        key={t}
                        onClick={() => { setMemoTopic(t); generateMemo(t); }}
                        disabled={memoLoading}
                        className="px-2 py-0.5 bg-white/10 rounded text-[9px] font-medium text-white/70 hover:bg-white/20 hover:text-white transition-colors disabled:opacity-40"
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                  {memoError && <p className="text-[10px] text-red-300 mt-1.5">{memoError}</p>}
                </>
              ) : (
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={14} className="text-green-300 shrink-0" />
                  <span className="text-[11px] text-teal-100 truncate">Memo ready — scroll down</span>
                  <button
                    onClick={() => { setMemoResult(null); setMemoTopic(""); }}
                    className="ml-auto text-[10px] text-white/50 hover:text-white/80"
                  >
                    New
                  </button>
                </div>
              )}
            </div>

            {/* Generated Memo Display */}
            {memoResult && (
              <div className="bg-white rounded-xl border border-teal-200 overflow-hidden">
                <div className="px-4 py-2.5 border-b border-teal-100 bg-teal-50 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <FileText size={13} className="text-teal-700" />
                    <span className="text-[11px] font-semibold text-teal-800">Investment Committee Memo</span>
                  </div>
                  <button onClick={() => { setMemoResult(null); setMemoTopic(""); }} className="text-teal-400 hover:text-teal-600">
                    <X size={13} />
                  </button>
                </div>
                <div className="px-4 py-3 prose prose-sm prose-gray max-w-none text-[12px] leading-relaxed [&_h1]:text-sm [&_h1]:font-bold [&_h1]:mb-2 [&_h1]:mt-0 [&_h2]:text-xs [&_h2]:font-bold [&_h2]:mt-3 [&_h2]:mb-1.5 [&_h3]:text-xs [&_h3]:font-semibold [&_h3]:mt-2 [&_h3]:mb-1 [&_p]:mb-1.5 [&_ul]:mb-1.5 [&_li]:mb-0.5 [&_strong]:text-gray-900">
                  <ReactMarkdown>{memoResult}</ReactMarkdown>
                </div>
              </div>
            )}

            <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col items-center">
              <ScoreGauge score={data.aggregate_score} direction={data.aggregate_direction} size="sm" />
              <div className="flex items-center gap-3 text-[10px] text-gray-500 mt-2">
                <span>{data.series_count} series</span>
                <span>{data.anomaly_count} anomalies</span>
                <span>{data.divergence_count} divergences</span>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-3 py-2 border-b border-gray-100">
                <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Domain Scorecards</span>
              </div>
              <div className="divide-y divide-gray-50">
                {scorecards.map((card: any) => (
                  <div key={card.domain} className="px-3 py-2.5 flex items-center justify-between hover:bg-gray-50/50 transition-colors">
                    <div className="flex items-center gap-2 min-w-0">
                      <TrendingUp size={12} className="text-gray-400 shrink-0" />
                      <span className="text-xs font-medium text-gray-800 truncate">{card.label || card.domain}</span>
                      {(card.alert_count || 0) > 0 && (
                        <span className="px-1 py-0.5 text-[8px] font-bold bg-red-100 text-red-700 rounded-full">{card.alert_count}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className={`text-xs font-bold font-mono ${card.score > 0 ? "text-green-600" : card.score < 0 ? "text-red-600" : "text-gray-500"}`}>
                        {card.score > 0 ? "+" : ""}{(card.score || 0).toFixed(1)}
                      </span>
                      <span className="text-[10px] text-gray-400">{DIRECTION_ICON[card.direction] || "->"}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {(data.cross_series_alerts?.length || 0) > 0 && (
              <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                <div className="px-3 py-2 border-b border-gray-100">
                  <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Divergences ({data.divergence_count})</span>
                </div>
                <div className="divide-y divide-gray-50">
                  {data.cross_series_alerts.slice(0, 4).map((d: any, i: number) => (
                    <div key={i} className="px-3 py-2.5">
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <ArrowUpDown size={10} className="text-orange-500" />
                        <span className="text-[11px] font-medium text-gray-800">
                          {d.pair_name?.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())}
                        </span>
                      </div>
                      <p className="text-[10px] text-gray-500 leading-snug">{d.description}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <p className="text-[10px] text-gray-400 text-center">
              {data.last_run?.finished_at ? `Updated: ${new Date(data.last_run.finished_at).toLocaleString()}` : ""}
            </p>
          </div>
        )}

        {data && tab === "anomalies" && (
          <div className="p-3 space-y-1.5">
            {anomalies.length === 0 && (
              <div className="bg-green-50 rounded-xl border border-green-200 px-4 py-6 text-center">
                <p className="text-xs text-green-700 font-medium">No active anomalies detected.</p>
              </div>
            )}
            {anomalies.map((a: any, i: number) => (
              <div key={i} className="bg-white rounded-lg border border-gray-200 px-3 py-2.5 hover:shadow-sm transition-shadow">
                <div className="flex items-center gap-1.5 mb-1">
                  <span className={`w-1.5 h-1.5 rounded-full ${SEVERITY_DOT[a.severity] || "bg-gray-400"}`} />
                  <span className="text-[11px] font-semibold text-gray-900">{a.series_name}</span>
                  <span className={`px-1.5 py-0.5 rounded-full text-[8px] font-bold ${
                    a.severity === "critical" ? "bg-red-100 text-red-700" : a.severity === "warning" ? "bg-orange-100 text-orange-700" : "bg-blue-100 text-blue-700"
                  }`}>
                    {a.severity.toUpperCase()}
                  </span>
                </div>
                <p className="text-[10px] text-gray-600 leading-snug">{a.description}</p>
              </div>
            ))}
          </div>
        )}

        {tab === "debate" && (
          <div className="p-3">
            <AgentDebate />
          </div>
        )}

        {/* Models Tab */}
        {tab === "models" && (
          <div className="p-3 space-y-3">
            {modelsLoading && (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-5 h-5 text-teal-700 animate-spin" />
              </div>
            )}

            {!modelsLoading && !modelsData && (
              <div className="bg-white rounded-xl border border-gray-200 p-6 text-center">
                <Cpu className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                <p className="text-xs text-gray-500 mb-3">Model status unavailable</p>
                <button onClick={fetchModelsStatus} className="text-xs text-teal-700 font-medium hover:underline">Retry</button>
              </div>
            )}

            {modelsData && (
              <>
                <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">ML Pipeline</span>
                    <span className="text-xs font-bold text-teal-700">{modelsData.ready}/{modelsData.total} ready</span>
                  </div>
                  <div className="flex h-2 rounded-full overflow-hidden bg-gray-100">
                    <div className="bg-teal-600 transition-all duration-500" style={{ width: `${(modelsData.ready / Math.max(modelsData.total, 1)) * 100}%` }} />
                  </div>
                </div>

                <div className="flex gap-2">
                  <button onClick={() => warmModel()} className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-teal-700 text-white rounded-lg text-[11px] font-medium hover:bg-teal-800 transition-colors">
                    <Play size={12} />Load All Models
                  </button>
                  <button onClick={runCompute} disabled={computeLoading || modelsData.ready === 0} className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-teal-700/10 text-teal-700 rounded-lg text-[11px] font-medium hover:bg-teal-700/20 transition-colors disabled:opacity-40">
                    {computeLoading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                    {computeLoading ? "Running..." : "Run Compute"}
                  </button>
                </div>

                {computeResult && (
                  <div className="bg-teal-50 rounded-xl border border-teal-200 px-3 py-2.5">
                    <span className="text-[10px] font-semibold text-teal-700 uppercase tracking-wider">
                      Last Compute ({computeResult.duration_ms}ms)
                    </span>
                    <div className="mt-1.5 space-y-1">
                      {computeResult.changepoint && (
                        <p className="text-[10px] text-teal-800">Changepoint: {computeResult.changepoint.series_with_changepoints || 0} series with regime shifts</p>
                      )}
                      {computeResult.isolation_forest && (
                        <p className="text-[10px] text-teal-800">IsoForest: {computeResult.isolation_forest.anomalies_detected || 0} anomalies across {computeResult.isolation_forest.series_affected || 0} series</p>
                      )}
                      {computeResult.elastic_net?.top_drivers && (
                        <p className="text-[10px] text-teal-800">Drivers: R²={computeResult.elastic_net.r_squared?.toFixed(2)}, top = {computeResult.elastic_net.top_drivers[0]?.feature || "n/a"}</p>
                      )}
                    </div>
                  </div>
                )}

                <div className="space-y-1.5">
                  {modelsData.models.map((model) => {
                    const statusCfg = STATUS_CONFIG[model.status] || STATUS_CONFIG.not_loaded;
                    const StatusIcon = statusCfg.icon;
                    const catColor = CATEGORY_COLORS[model.category] || CATEGORY_COLORS.rag;
                    return (
                      <div key={model.name} className="bg-white rounded-lg border border-gray-200 px-3 py-2.5 hover:shadow-sm transition-shadow">
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2 min-w-0">
                            <StatusIcon size={14} className={`shrink-0 ${statusCfg.color} ${model.status === "loading" ? "animate-spin" : ""}`} />
                            <span className="text-[11px] font-bold text-gray-900 truncate">
                              {model.name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                            </span>
                            <span className={`px-1.5 py-0.5 rounded-full text-[8px] font-bold ${catColor.bg} ${catColor.text}`}>
                              {model.category.toUpperCase()}
                            </span>
                          </div>
                          {model.size_mb && (
                            <span className="text-[9px] text-gray-400 font-mono shrink-0">{model.size_mb < 1 ? "<1" : model.size_mb} MB</span>
                          )}
                        </div>
                        <p className="text-[10px] text-gray-500 leading-snug mb-1.5">{model.description}</p>
                        <div className="flex items-center gap-3 text-[9px] text-gray-400">
                          <span className={`font-semibold ${statusCfg.color}`}>{statusCfg.label}</span>
                          {model.last_run_ms !== null && <span>{model.last_run_ms}ms</span>}
                          {model.loaded_at && <span>{new Date(model.loaded_at).toLocaleTimeString()}</span>}
                          {model.status !== "ready" && model.status !== "loading" && (
                            <button onClick={() => warmModel(model.name)} className="text-teal-700 font-semibold hover:underline">Load</button>
                          )}
                        </div>
                        {model.error && <p className="text-[9px] text-red-500 mt-1 truncate" title={model.error}>{model.error}</p>}
                      </div>
                    );
                  })}
                </div>

                <button onClick={fetchModelsStatus} className="w-full flex items-center justify-center gap-1 text-[10px] text-teal-700 font-medium hover:underline py-1">
                  <RefreshCw size={10} />Refresh status
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-teal-700/10 bg-teal-50 px-3 py-2 shrink-0">
        <button
          onClick={() => router.push("/signals")}
          className="w-full flex items-center justify-center gap-1.5 text-[11px] text-teal-700 font-semibold hover:text-teal-800 transition-colors py-1"
        >
          Open full dashboard
          <ChevronRight size={12} />
        </button>
      </div>
    </div>
  );
}
