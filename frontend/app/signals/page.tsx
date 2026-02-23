"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, RefreshCw, AlertTriangle } from "lucide-react";
import ScoreGauge from "@/components/signals/ScoreGauge";
import RadarChart from "@/components/signals/RadarChart";
import DomainCard from "@/components/signals/DomainCard";
import AnomalyTable from "@/components/signals/AnomalyTable";
import AgentDebate from "@/components/signals/AgentDebate";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

function authHeaders(): Record<string, string> {
  const token =
    typeof window !== "undefined"
      ? localStorage.getItem("jadwachat_token")
      : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
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

export default function SignalsDashboard() {
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboard = async () => {
    try {
      const res = await fetch(`${API_BASE}/signals/dashboard`, {
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const res = await fetch(`${API_BASE}/signals/refresh`, {
        method: "POST",
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`Refresh failed: ${res.status}`);
      // Reload dashboard after refresh
      await fetchDashboard();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchDashboard();
  }, []);

  // Override the body overflow-hidden from root layout so this page scrolls
  useEffect(() => {
    document.body.style.overflow = "auto";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <RefreshCw className="w-8 h-8 text-jadwa-brown animate-spin" />
          <p className="text-sm text-gray-500">Loading Signal Dashboard...</p>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-white rounded-xl shadow-sm border p-8 max-w-md text-center">
          <AlertTriangle className="w-12 h-12 text-orange-400 mx-auto mb-3" />
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Dashboard Unavailable</h2>
          <p className="text-sm text-gray-500 mb-4">{error}</p>
          <button
            onClick={fetchDashboard}
            className="px-4 py-2 bg-jadwa-brown text-white rounded-lg text-sm font-medium hover:bg-jadwa-brown-dark transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const scorecards = data?.scorecards || [];
  const radarPoints = scorecards.map((c) => ({
    label: c.label || c.domain,
    score: c.score || 0,
  }));

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push("/")}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              title="Back to Chat"
            >
              <ArrowLeft size={18} className="text-gray-600" />
            </button>
            <div>
              <h1 className="text-lg font-bold text-gray-900">
                Macro Signal Dashboard
              </h1>
              <p className="text-[11px] text-gray-400">
                {data?.report_date
                  ? `Report: ${data.report_date}`
                  : ""}
                {data?.last_run?.finished_at
                  ? ` · Last updated: ${new Date(data.last_run.finished_at).toLocaleString()}`
                  : ""}
              </p>
            </div>
          </div>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-2 px-3 py-2 bg-jadwa-brown text-white rounded-lg text-sm font-medium hover:bg-jadwa-brown-dark transition-colors disabled:opacity-50"
          >
            <RefreshCw
              size={14}
              className={refreshing ? "animate-spin" : ""}
            />
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* Top Row: Aggregate Score + Radar Chart */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Aggregate Score Gauge */}
          <div className="bg-white rounded-xl border border-gray-200 p-6 flex flex-col items-center justify-center">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">
              Aggregate Score
            </h2>
            <ScoreGauge
              score={data?.aggregate_score || 0}
              direction={data?.aggregate_direction || "stable"}
              size="lg"
            />
            <div className="mt-4 flex items-center gap-4 text-xs text-gray-500">
              <span>{data?.series_count || 0} series</span>
              <span>·</span>
              <span>{data?.anomaly_count || 0} anomalies</span>
              <span>·</span>
              <span>{data?.divergence_count || 0} divergences</span>
            </div>
          </div>

          {/* Radar Chart */}
          <div className="bg-white rounded-xl border border-gray-200 p-6 flex flex-col items-center justify-center">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">
              Domain Radar
            </h2>
            {radarPoints.length >= 3 ? (
              <RadarChart points={radarPoints} size={240} />
            ) : (
              <p className="text-sm text-gray-400">Not enough data for radar chart</p>
            )}
            {/* Domain Score Summary below radar on mobile */}
            <div className="sm:hidden mt-4 w-full space-y-2">
              {scorecards.map((c) => (
                <div key={c.domain} className="flex justify-between text-xs">
                  <span className="text-gray-600">{c.label || c.domain}</span>
                  <span
                    className={`font-semibold ${
                      c.score > 0
                        ? "text-green-600"
                        : c.score < 0
                        ? "text-red-600"
                        : "text-gray-500"
                    }`}
                  >
                    {c.score > 0 ? "+" : ""}
                    {(c.score || 0).toFixed(1)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Domain Scorecards */}
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-3">
            Domain Scorecards
          </h2>
          <div className="space-y-3">
            {scorecards.map((card) => (
              <DomainCard
                key={card.domain}
                domain={card.domain}
                label={card.label || card.domain}
                score={card.score || 0}
                direction={card.direction || "stable"}
                priorScore={card.prior_score}
                alertCount={card.alert_count || 0}
                components={card.components || {}}
              />
            ))}
          </div>
        </div>

        {/* Anomaly Alerts */}
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-3">
            Anomaly Alerts
          </h2>
          <AnomalyTable
            anomalies={data?.anomalies || []}
            onAsk={(question) => {
              // Navigate to chat with pre-filled question
              router.push(`/?q=${encodeURIComponent(question)}`);
            }}
          />
        </div>

        {/* Agent Debate */}
        <AgentDebate />

        {/* Cross-Series Divergences */}
        {(data?.cross_series_alerts?.length || 0) > 0 && (
          <div>
            <h2 className="text-sm font-semibold text-gray-700 mb-3">
              Cross-Series Divergences
            </h2>
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden divide-y divide-gray-100">
              {data?.cross_series_alerts?.map((d, i) => (
                <div key={i} className="px-5 py-4 hover:bg-gray-50/50">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-2 h-2 rounded-full bg-orange-500" />
                    <span className="text-sm font-medium text-gray-900">
                      {d.pair_name?.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())}
                    </span>
                    <span className="text-[10px] text-gray-400 font-mono">
                      r: {d.long_run_correlation} → {d.recent_correlation}
                    </span>
                    <span className="text-[10px] font-semibold text-orange-600">
                      Δ {d.divergence?.toFixed(2)}
                    </span>
                  </div>
                  <p className="text-xs text-gray-600">{d.description}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="text-center py-4 text-[10px] text-gray-400">
          JadwaChat Quant Signal Engine v1.0
          {data?.last_run?.duration_ms
            ? ` · Pipeline: ${data.last_run.duration_ms}ms`
            : ""}
        </div>
      </main>
    </div>
  );
}

