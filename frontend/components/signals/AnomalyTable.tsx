"use client";

interface Anomaly {
  series_id: string;
  series_name: string;
  date: string;
  alert_type: string;
  severity: string;
  z_score?: number | null;
  description: string;
}

interface AnomalyTableProps {
  anomalies: Anomaly[];
  onAsk?: (question: string) => void;
}

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-100 text-red-800 border-red-200",
  warning: "bg-orange-100 text-orange-800 border-orange-200",
  watch: "bg-blue-100 text-blue-800 border-blue-200",
};

const SEVERITY_DOT: Record<string, string> = {
  critical: "bg-red-500",
  warning: "bg-orange-500",
  watch: "bg-blue-500",
};

function formatAlertType(type: string): string {
  return type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function AnomalyTable({ anomalies, onAsk }: AnomalyTableProps) {
  if (anomalies.length === 0) {
    return (
      <div className="bg-green-50 border border-green-200 rounded-xl px-5 py-4">
        <p className="text-sm text-green-700 font-medium">
          No active anomalies detected. All series within normal ranges.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100 bg-gray-50">
        <h3 className="text-sm font-semibold text-gray-700">
          Anomaly Alerts ({anomalies.length})
        </h3>
      </div>
      <div className="divide-y divide-gray-100">
        {anomalies.map((a, i) => (
          <div key={i} className="px-5 py-3.5 hover:bg-gray-50/50 transition-colors">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`w-2 h-2 rounded-full ${SEVERITY_DOT[a.severity] || "bg-gray-400"}`}
                  />
                  <span className="text-sm font-medium text-gray-900">
                    {a.series_name}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                      SEVERITY_STYLES[a.severity] || "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {a.severity.toUpperCase()}
                  </span>
                  <span className="text-[10px] text-gray-400 font-mono">
                    {formatAlertType(a.alert_type)}
                  </span>
                </div>
                <p className="text-xs text-gray-600 leading-relaxed">
                  {a.description}
                </p>
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0">
                {a.z_score !== null && a.z_score !== undefined && (
                  <span className="text-xs font-mono text-gray-500">
                    z={a.z_score > 0 ? "+" : ""}
                    {a.z_score.toFixed(1)}
                  </span>
                )}
                {onAsk && (
                  <button
                    onClick={() =>
                      onAsk(`Tell me more about the ${a.alert_type} anomaly in ${a.series_name}`)
                    }
                    className="text-[10px] text-jadwa-brown hover:text-jadwa-brown-dark font-medium hover:underline"
                  >
                    Ask JadwaChat →
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}



