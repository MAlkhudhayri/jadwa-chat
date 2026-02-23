"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  MessageSquare,
  RefreshCw,
  Users,
  Send,
  CheckCircle2,
  Zap,
  FileText,
  Loader2,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";

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

// ── Types ───────────────────────────────────────────────────────────────────

interface Message {
  agent_id: string;
  name: string;
  title: string;
  emoji: string;
  color: string;
  message: string;
  stance?: string;
  role: "agent" | "user" | "scenario";
}

interface Consensus {
  reached: boolean;
  majority_stance: string | null;
  percentage: number;
  breakdown: Record<string, number>;
}

interface ConvictionEntry {
  round: number;
  stances: Record<string, string>;
}

interface Scenario {
  id: string;
  label: string;
}

interface DebateSession {
  session_id: string;
  topic: string | null;
  round: number;
  status: string;
  consensus: Consensus;
  stances: Record<string, string>;
  conversation: Message[];
  conviction_history: ConvictionEntry[];
  total_tokens: number;
  max_rounds: number;
  note?: string;
  available_scenarios: Scenario[];
  scenarios_applied: string[];
}

// ── Agent visual config (no emojis) ─────────────────────────────────────────

const AGENT_AVATARS: Record<string, { initials: string; color: string }> = {
  sniper:     { initials: "SN", color: "#1B365D" },
  scalper:    { initials: "SC", color: "#F59E0B" },
  guardian:   { initials: "GD", color: "#DC2626" },
  strategist: { initials: "ST", color: "#059669" },
  contrarian: { initials: "CN", color: "#7C3AED" },
  quant:      { initials: "QT", color: "#0284C7" },
};

// ── Constants ───────────────────────────────────────────────────────────────

const STANCE_STYLES: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  BULLISH: { bg: "bg-green-100", text: "text-green-700", label: "Bullish" },
  BEARISH: { bg: "bg-red-100", text: "text-red-700", label: "Bearish" },
  NEUTRAL: { bg: "bg-gray-100", text: "text-gray-600", label: "Neutral" },
};

const AGENT_ORDER = ["sniper", "scalper", "guardian", "strategist", "contrarian", "quant"];

const TOPIC_SUGGESTIONS = [
  "Should we increase Saudi equity allocation?",
  "Is the oil scorecard misleading?",
  "What's the biggest risk the scorecards aren't capturing?",
  "Is banking sector stress being underpriced?",
  "Should we hedge oil exposure now?",
];

// ── Scripted Demo ───────────────────────────────────────────────────────────

const DEMO_MESSAGES: Message[] = [
  {
    agent_id: "sniper", name: "The Sniper", title: "High-Conviction Strategist",
    emoji: "", color: "#1B365D", role: "agent", stance: "BULLISH",
    message: "The aggregate score at +27.3 is the highest I've seen in two cycles. Oil domain at +45 with improving direction and banking holding steady — this is a structural re-rating, not noise. I'm positioned long.",
  },
  {
    agent_id: "scalper", name: "The Scalper", title: "Momentum Trader",
    emoji: "", color: "#F59E0B", role: "agent", stance: "BULLISH",
    message: "Momentum confirms the Sniper's thesis. Brent MoM is +3.2% with a positive z-score, and monetary reserves are accelerating. Short-term flow is clearly risk-on. Riding this wave.",
  },
  {
    agent_id: "guardian", name: "The Guardian", title: "Risk Manager",
    emoji: "", color: "#DC2626", role: "agent", stance: "NEUTRAL",
    message: "49 active anomalies and 4 cross-series divergences give me pause. The oil-reserves correlation just broke down — r dropped from 0.82 to 0.41. That's a warning sign everyone is ignoring. I'm not selling, but I'm not adding either.",
  },
  {
    agent_id: "strategist", name: "The Strategist", title: "Macro Analyst",
    emoji: "", color: "#059669", role: "agent", stance: "BULLISH",
    message: "The Guardian raises a valid point on divergences, but structurally Saudi macro is in a sweet spot: oil revenues funding Vision 2030 investment, banking credit growth healthy, inflation contained. The divergence is likely temporary. Constructive.",
  },
  {
    agent_id: "contrarian", name: "The Contrarian", title: "Devil's Advocate",
    emoji: "", color: "#7C3AED", role: "agent", stance: "BEARISH",
    message: "Everyone is bullish on the same narrative. That's exactly when you should worry. The inflation scorecard is the weakest at -5.2, and nobody here has mentioned global demand risk. If China slows further, this entire oil-driven thesis unravels.",
  },
  {
    agent_id: "quant", name: "The Quant", title: "Data Scientist",
    emoji: "", color: "#0284C7", role: "agent", stance: "BULLISH",
    message: "Statistically: 4 of 5 domains positive, aggregate z-score above +1.0, 73rd percentile on a 36-month basis. The anomaly count is elevated but 80% are watch-level, not critical. The numbers support a bullish tilt with a 67% confidence band.",
  },
];

function buildDemoSession(): DebateSession {
  const stances: Record<string, string> = {};
  for (const m of DEMO_MESSAGES) stances[m.agent_id] = m.stance || "NEUTRAL";
  const breakdown: Record<string, number> = {};
  for (const s of Object.values(stances)) breakdown[s] = (breakdown[s] || 0) + 1;
  const total = Object.values(breakdown).reduce((a, b) => a + b, 0);
  const majority = Object.entries(breakdown).sort((a, b) => b[1] - a[1])[0];

  return {
    session_id: "demo",
    topic: "Saudi Macro Outlook — Q1 2026",
    round: 1,
    status: "demo",
    consensus: {
      reached: majority[1] / total >= 0.7,
      majority_stance: majority[0],
      percentage: Math.round((majority[1] / total) * 1000) / 10,
      breakdown,
    },
    stances,
    conversation: DEMO_MESSAGES,
    conviction_history: [{ round: 1, stances: { ...stances } }],
    total_tokens: 0,
    max_rounds: 8,
    available_scenarios: [],
    scenarios_applied: [],
  };
}

// ── Sub-components ──────────────────────────────────────────────────────────

function AgentAvatar({ agentId, color, isUser }: { agentId: string; color: string; isUser?: boolean }) {
  if (isUser) {
    return (
      <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center shrink-0 mt-0.5">
        <span className="text-[10px] font-bold text-blue-700">YOU</span>
      </div>
    );
  }
  const avatar = AGENT_AVATARS[agentId];
  return (
    <div
      className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
      style={{ backgroundColor: `${color}18` }}
    >
      <span className="text-[10px] font-bold" style={{ color }}>
        {avatar?.initials || agentId.slice(0, 2).toUpperCase()}
      </span>
    </div>
  );
}

function StanceBadge({ stance }: { stance?: string }) {
  if (!stance) return null;
  const s = STANCE_STYLES[stance] || STANCE_STYLES.NEUTRAL;
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${s.bg} ${s.text}`}>
      {s.label}
    </span>
  );
}

function ConsensusBar({ consensus }: { consensus: Consensus }) {
  const { breakdown, percentage, majority_stance, reached } = consensus;
  const total = Object.values(breakdown).reduce((a, b) => a + b, 0) || 1;

  return (
    <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          Consensus
        </span>
        {reached ? (
          <span className="flex items-center gap-1 text-xs font-bold text-green-600">
            <CheckCircle2 size={14} />
            {percentage}% {majority_stance}
          </span>
        ) : (
          <span className="text-xs text-gray-400">
            {percentage}% — need 70%
          </span>
        )}
      </div>
      <div className="flex h-3 rounded-full overflow-hidden bg-gray-100">
        {(breakdown.BULLISH || 0) > 0 && (
          <div className="bg-green-500 transition-all duration-500" style={{ width: `${((breakdown.BULLISH || 0) / total) * 100}%` }} />
        )}
        {(breakdown.NEUTRAL || 0) > 0 && (
          <div className="bg-gray-400 transition-all duration-500" style={{ width: `${((breakdown.NEUTRAL || 0) / total) * 100}%` }} />
        )}
        {(breakdown.BEARISH || 0) > 0 && (
          <div className="bg-red-500 transition-all duration-500" style={{ width: `${((breakdown.BEARISH || 0) / total) * 100}%` }} />
        )}
      </div>
      <div className="flex justify-between mt-1.5 text-[10px] text-gray-500">
        <span className="text-green-600 font-medium">{breakdown.BULLISH || 0} Bullish</span>
        <span className="text-gray-500 font-medium">{breakdown.NEUTRAL || 0} Neutral</span>
        <span className="text-red-600 font-medium">{breakdown.BEARISH || 0} Bearish</span>
      </div>
    </div>
  );
}

function ConvictionChart({ history }: { history: ConvictionEntry[] }) {
  if (history.length < 2) return null;

  const stanceToY = (s: string) => (s === "BULLISH" ? 0 : s === "NEUTRAL" ? 1 : 2);
  const agents = AGENT_ORDER;

  const w = 240;
  const h = 72;
  const padX = 24;
  const padY = 8;
  const plotW = w - padX * 2;
  const plotH = h - padY * 2;
  const xStep = history.length > 1 ? plotW / (history.length - 1) : plotW;

  return (
    <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
      <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">
        Conviction Evolution
      </span>
      <svg width={w} height={h} className="w-full mt-1" viewBox={`0 0 ${w} ${h}`}>
        <text x={2} y={padY + 4} fontSize={8} fill="#9CA3AF">Bull</text>
        <text x={2} y={padY + plotH / 2 + 3} fontSize={8} fill="#9CA3AF">Neut</text>
        <text x={2} y={padY + plotH + 3} fontSize={8} fill="#9CA3AF">Bear</text>
        {[0, 1, 2].map((y) => (
          <line key={y} x1={padX} y1={padY + (y / 2) * plotH} x2={padX + plotW} y2={padY + (y / 2) * plotH} stroke="#F3F4F6" strokeWidth={1} />
        ))}
        {agents.map((agentId) => {
          const points = history.map((entry, i) => {
            const stance = entry.stances[agentId] || "NEUTRAL";
            return `${padX + i * xStep},${padY + (stanceToY(stance) / 2) * plotH}`;
          });
          return <polyline key={agentId} points={points.join(" ")} fill="none" stroke={AGENT_AVATARS[agentId]?.color || "#999"} strokeWidth={1.5} strokeLinejoin="round" opacity={0.8} />;
        })}
        {agents.map((agentId) => {
          const latest = history[history.length - 1];
          const stance = latest.stances[agentId] || "NEUTRAL";
          return <circle key={agentId} cx={padX + (history.length - 1) * xStep} cy={padY + (stanceToY(stance) / 2) * plotH} r={3} fill={AGENT_AVATARS[agentId]?.color || "#999"} />;
        })}
        {history.map((entry, i) => (
          <text key={i} x={padX + i * xStep} y={h - 1} fontSize={7} fill="#9CA3AF" textAnchor="middle">R{entry.round}</text>
        ))}
      </svg>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1">
        {agents.map((id) => (
          <span key={id} className="flex items-center gap-1 text-[9px] text-gray-500">
            <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: AGENT_AVATARS[id]?.color }} />
            {id.charAt(0).toUpperCase() + id.slice(1)}
          </span>
        ))}
      </div>
    </div>
  );
}

function SplitView({ messages }: { messages: Message[] }) {
  const agentMessages = messages.filter((m) => m.role === "agent");
  const lastByAgent: Record<string, Message> = {};
  for (const m of agentMessages) lastByAgent[m.agent_id] = m;

  const bulls = Object.values(lastByAgent).filter((m) => m.stance === "BULLISH");
  const bears = Object.values(lastByAgent).filter((m) => m.stance === "BEARISH");
  const neutrals = Object.values(lastByAgent).filter((m) => m.stance === "NEUTRAL");

  const renderCard = (msg: Message) => (
    <div key={msg.agent_id} className="flex items-start gap-2 mb-2">
      <AgentAvatar agentId={msg.agent_id} color={msg.color} />
      <div className="min-w-0">
        <span className="text-[11px] font-bold" style={{ color: msg.color }}>{msg.name}</span>
        <p className="text-[11px] text-gray-600 leading-snug mt-0.5">{msg.message}</p>
      </div>
    </div>
  );

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="grid grid-cols-3 divide-x divide-gray-100">
        <div className="p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <span className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-[10px] font-bold text-green-700 uppercase">Bullish ({bulls.length})</span>
          </div>
          {bulls.length > 0 ? bulls.map(renderCard) : <p className="text-[10px] text-gray-300 italic">No bulls</p>}
        </div>
        <div className="p-3 bg-gray-50/30">
          <div className="flex items-center gap-1.5 mb-2">
            <span className="w-2 h-2 rounded-full bg-gray-400" />
            <span className="text-[10px] font-bold text-gray-500 uppercase">Neutral ({neutrals.length})</span>
          </div>
          {neutrals.length > 0 ? neutrals.map(renderCard) : <p className="text-[10px] text-gray-300 italic">No neutrals</p>}
        </div>
        <div className="p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <span className="w-2 h-2 rounded-full bg-red-500" />
            <span className="text-[10px] font-bold text-red-700 uppercase">Bearish ({bears.length})</span>
          </div>
          {bears.length > 0 ? bears.map(renderCard) : <p className="text-[10px] text-gray-300 italic">No bears</p>}
        </div>
      </div>
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function AgentDebate() {
  const [session, setSession] = useState<DebateSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [sendingMessage, setSendingMessage] = useState(false);
  const [userInput, setUserInput] = useState("");
  const [topicInput, setTopicInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [memo, setMemo] = useState<string | null>(null);
  const [memoLoading, setMemoLoading] = useState(false);
  const [visibleCount, setVisibleCount] = useState(0);
  const [viewMode, setViewMode] = useState<"thread" | "split">("thread");
  const [isDemo, setIsDemo] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const autoStarted = useRef(false);

  // Auto-start the demo on first mount
  useEffect(() => {
    if (autoStarted.current) return;
    autoStarted.current = true;
    setIsDemo(true);
    setSession(buildDemoSession());
    setVisibleCount(0);
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [visibleCount, session?.conversation?.length]);

  // Stagger reveal — slower pace for demo so it feels like real typing
  useEffect(() => {
    if (!session) return;
    const total = session.conversation.length;
    if (visibleCount < total) {
      const delay = isDemo ? 1200 : 350;
      const timer = setTimeout(() => setVisibleCount((v) => v + 1), delay);
      return () => clearTimeout(timer);
    }
  }, [session, visibleCount, isDemo]);

  const resetAll = useCallback(() => {
    setSession(null);
    setTopicInput("");
    setMemo(null);
    setVisibleCount(0);
    setIsDemo(false);
    setError(null);
  }, []);

  const startDemo = () => {
    resetAll();
    setTimeout(() => {
      setIsDemo(true);
      setSession(buildDemoSession());
      setVisibleCount(0);
    }, 50);
  };

  const startDebate = async (topic?: string) => {
    setLoading(true);
    setError(null);
    setMemo(null);
    setVisibleCount(0);
    setIsDemo(false);
    try {
      const res = await fetch(`${API_BASE}/signals/debate`, {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({ topic: topic || topicInput.trim() || undefined }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSession(data);
      setVisibleCount(0);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const sendMessage = async () => {
    if (!session || !userInput.trim() || sendingMessage || isDemo) return;
    const message = userInput.trim();
    setUserInput("");
    setSendingMessage(true);
    try {
      const res = await fetch(
        `${API_BASE}/signals/debate/${session.session_id}/user`,
        { method: "POST", headers: jsonAuthHeaders(), body: JSON.stringify({ message }) }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const prevLen = session.conversation.length;
      setSession(data);
      setVisibleCount(prevLen + 1);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSendingMessage(false);
    }
  };

  const continueDebate = async () => {
    if (!session || isDemo) return;
    setSendingMessage(true);
    try {
      const res = await fetch(
        `${API_BASE}/signals/debate/${session.session_id}/round`,
        { method: "POST", headers: jsonAuthHeaders() }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const prevLen = session.conversation.length;
      setSession(data);
      setVisibleCount(prevLen);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSendingMessage(false);
    }
  };

  const injectScenario = async (scenarioId: string) => {
    if (!session || isDemo) return;
    setSendingMessage(true);
    try {
      const res = await fetch(
        `${API_BASE}/signals/debate/${session.session_id}/scenario`,
        { method: "POST", headers: jsonAuthHeaders(), body: JSON.stringify({ scenario_id: scenarioId }) }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const prevLen = session.conversation.length;
      setSession(data);
      setVisibleCount(prevLen);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSendingMessage(false);
    }
  };

  const generateMemo = async () => {
    if (!session || isDemo) return;
    setMemoLoading(true);
    try {
      const res = await fetch(
        `${API_BASE}/signals/debate/${session.session_id}/memo`,
        { method: "POST", headers: jsonAuthHeaders() }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setMemo(data.memo || data.error || "Failed to generate memo.");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setMemoLoading(false);
    }
  };

  // ── Not yet started (shown after user resets) ──────────────────────
  if (!session && !loading) {
    return (
      <div className="bg-gradient-to-br from-gray-50 to-white rounded-xl border border-gray-200 p-6 sm:p-8">
        <div className="text-center">
          <div className="flex justify-center mb-4">
            <div className="w-14 h-14 rounded-2xl bg-jadwa-brown/10 flex items-center justify-center">
              <Users className="w-7 h-7 text-jadwa-brown" />
            </div>
          </div>
          <h3 className="text-lg font-bold text-gray-900 mb-1">Agent Debate</h3>
          <p className="text-sm text-gray-500 mb-4 max-w-lg mx-auto">
            6 AI investment personas debate the market signals until 70% consensus.
            Set a topic, inject scenarios, and jump in anytime.
          </p>

          {/* Agent tags with color dots */}
          <div className="flex flex-wrap justify-center gap-1.5 mb-5">
            {AGENT_ORDER.map((id) => {
              const av = AGENT_AVATARS[id];
              return (
                <span key={id} className="flex items-center gap-1.5 px-2.5 py-1 bg-gray-50 border border-gray-200 rounded-full text-[10px] text-gray-600 font-medium">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: av.color }} />
                  {id.charAt(0).toUpperCase() + id.slice(1)}
                </span>
              );
            })}
          </div>

          {/* Topic input */}
          <div className="max-w-md mx-auto mb-3">
            <input
              type="text"
              value={topicInput}
              onChange={(e) => setTopicInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") startDebate(); }}
              placeholder="Set a debate topic (optional)..."
              className="w-full px-4 py-2.5 text-sm bg-white border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-jadwa-brown/20 focus:border-jadwa-brown/30 placeholder:text-gray-400"
            />
          </div>

          {/* Topic suggestions */}
          <div className="flex flex-wrap justify-center gap-1.5 mb-5">
            {TOPIC_SUGGESTIONS.map((t) => (
              <button
                key={t}
                onClick={() => { setTopicInput(t); startDebate(t); }}
                className="px-2.5 py-1 bg-jadwa-brown/5 text-jadwa-brown rounded-lg text-[10px] font-medium hover:bg-jadwa-brown/10 transition-colors"
              >
                {t}
              </button>
            ))}
          </div>

          <div className="flex items-center justify-center gap-3">
            <button
              onClick={startDemo}
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-white text-jadwa-brown border border-jadwa-brown/20 rounded-lg text-sm font-medium hover:bg-jadwa-brown/5 transition-colors"
            >
              <RefreshCw size={14} />
              Replay Demo
            </button>
            <button
              onClick={() => startDebate()}
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-jadwa-brown text-white rounded-lg text-sm font-medium hover:bg-jadwa-brown-dark transition-colors shadow-sm"
            >
              <MessageSquare size={16} />
              Start Live Debate
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-8">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 text-jadwa-brown animate-spin mx-auto mb-3" />
          <p className="text-sm text-gray-500">Agents are taking their positions...</p>
          {topicInput && <p className="text-xs text-gray-400 mt-1">Topic: {topicInput}</p>}
        </div>
      </div>
    );
  }

  if (!session) return null;

  const isActive = session.status === "active";
  const isConsensus = session.status === "consensus_reached";
  const isMaxRounds = session.status === "max_rounds";
  const isDone = isConsensus || isMaxRounds;
  const visibleMessages = session.conversation.slice(0, visibleCount);

  const demoTyping = isDemo && visibleCount < session.conversation.length;
  const nextAgent = demoTyping ? session.conversation[visibleCount] : null;

  return (
    <div className="space-y-3">
      {/* Keyframe animations */}
      <style>{`
        @keyframes chatPop {
          0%   { opacity: 0; transform: translateY(16px) scale(0.96); }
          50%  { opacity: 1; transform: translateY(-3px) scale(1.01); }
          100% { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes fadeIn {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        @keyframes typingDot {
          0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
          40% { opacity: 1; transform: scale(1); }
        }
        .chat-pop { animation: chatPop 0.45s cubic-bezier(0.34, 1.56, 0.64, 1) both; }
        .fade-in  { animation: fadeIn 0.5s ease both; }
      `}</style>

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <Users size={16} />
            Agent Debate
            {isDemo && (
              <span className="px-2 py-0.5 bg-jadwa-brown/10 text-jadwa-brown rounded-full text-[10px] font-bold">
                DEMO
              </span>
            )}
            {!isDemo && (
              <span className="text-[10px] text-gray-400 font-normal">
                Round {session.round}/{session.max_rounds}
              </span>
            )}
          </h2>
          {session.topic && (
            <p className="text-xs text-jadwa-brown font-medium mt-0.5 ml-6">{session.topic}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex bg-gray-100 rounded-lg p-0.5 text-[10px]">
            <button
              onClick={() => setViewMode("thread")}
              className={`px-2.5 py-1 rounded-md font-medium transition-colors ${viewMode === "thread" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"}`}
            >
              Thread
            </button>
            <button
              onClick={() => setViewMode("split")}
              className={`px-2.5 py-1 rounded-md font-medium transition-colors ${viewMode === "split" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"}`}
            >
              Bulls vs Bears
            </button>
          </div>
          <button
            onClick={resetAll}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-jadwa-brown hover:bg-jadwa-brown/5 rounded-lg transition-colors font-medium"
          >
            <RefreshCw size={12} />
            {isDemo ? "Reset" : "New"}
          </button>
        </div>
      </div>

      <ConsensusBar consensus={session.consensus} />
      <ConvictionChart history={session.conviction_history} />
      {viewMode === "split" && <SplitView messages={session.conversation} />}

      {isConsensus && (
        <div className="bg-green-50 border border-green-200 rounded-xl px-5 py-4 text-center">
          <CheckCircle2 className="w-8 h-8 text-green-500 mx-auto mb-2" />
          <p className="text-sm font-bold text-green-800">
            Consensus Reached: {session.consensus.percentage}% {session.consensus.majority_stance}
          </p>
          <p className="text-xs text-green-600 mt-1">
            After {session.round} round{session.round > 1 ? "s" : ""} of debate.
          </p>
        </div>
      )}

      {isMaxRounds && !isConsensus && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-5 py-3 text-center">
          <p className="text-sm font-medium text-yellow-800">
            Max rounds reached ({session.consensus.percentage}% {session.consensus.majority_stance})
          </p>
        </div>
      )}

      {/* Scenario buttons */}
      {isActive && !isDemo && (session.available_scenarios?.length || 0) > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[10px] text-gray-400 font-semibold uppercase self-center mr-1">What if:</span>
          {session.available_scenarios.map((s) => (
            <button
              key={s.id}
              onClick={() => injectScenario(s.id)}
              disabled={sendingMessage}
              className="flex items-center gap-1 px-2.5 py-1 bg-amber-50 text-amber-700 border border-amber-200 rounded-lg text-[10px] font-medium hover:bg-amber-100 transition-colors disabled:opacity-40"
            >
              <Zap size={10} />
              {s.label}
            </button>
          ))}
        </div>
      )}

      {/* Chat Thread */}
      {viewMode === "thread" && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="max-h-[600px] overflow-y-auto divide-y divide-gray-50">
            {visibleMessages.map((msg, i) => {
              const isUser = msg.role === "user";
              const isScenario = msg.role === "scenario";

              if (isScenario) {
                return (
                  <div key={i} className="px-4 py-3 bg-amber-50/60 chat-pop">
                    <div className="flex items-start gap-3">
                      <div className="w-8 h-8 rounded-lg bg-amber-100 flex items-center justify-center shrink-0 mt-0.5">
                        <Zap size={12} className="text-amber-600" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-sm font-bold text-amber-700">Scenario</span>
                          <span className="text-[10px] text-amber-500 font-medium">{msg.title}</span>
                        </div>
                        <p className="text-sm text-amber-800 leading-relaxed">{msg.message}</p>
                      </div>
                    </div>
                  </div>
                );
              }

              return (
                <div
                  key={i}
                  className={`px-4 py-3 chat-pop ${isUser ? "bg-blue-50/50" : "hover:bg-gray-50/50"} transition-colors`}
                >
                  <div className="flex items-start gap-3">
                    <AgentAvatar agentId={msg.agent_id} color={msg.color} isUser={isUser} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-sm font-bold" style={{ color: isUser ? "#1D4ED8" : msg.color }}>
                          {msg.name}
                        </span>
                        <span className="text-[10px] text-gray-400 font-medium uppercase">{msg.title}</span>
                        {msg.stance && <StanceBadge stance={msg.stance} />}
                      </div>
                      <p className="text-sm text-gray-700 leading-relaxed">{msg.message}</p>
                    </div>
                  </div>
                </div>
              );
            })}

            {/* Typing indicator — shows which agent is "thinking" next */}
            {(sendingMessage || demoTyping || (!isDemo && visibleCount < session.conversation.length)) && (
              <div className="px-4 py-3 flex items-center gap-3 fade-in">
                {nextAgent ? (
                  <AgentAvatar agentId={nextAgent.agent_id} color={nextAgent.color} />
                ) : (
                  <div className="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center">
                    <RefreshCw size={14} className="text-gray-400 animate-spin" />
                  </div>
                )}
                <div className="flex items-center gap-1">
                  <span className="text-[11px] font-medium" style={{ color: nextAgent?.color || "#9CA3AF" }}>
                    {nextAgent?.name || "Agent"}
                  </span>
                  <span className="text-[11px] text-gray-400 ml-0.5">is typing</span>
                  <span className="flex gap-0.5 ml-1">
                    {[0, 1, 2].map((dot) => (
                      <span
                        key={dot}
                        className="w-1 h-1 rounded-full bg-gray-400"
                        style={{ animation: `typingDot 1.2s infinite ${dot * 0.2}s` }}
                      />
                    ))}
                  </span>
                </div>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          {/* Input area */}
          {isActive && !isDemo && (
            <div className="border-t border-gray-200 p-3">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={userInput}
                  onChange={(e) => setUserInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
                  placeholder="Join the debate..."
                  className="flex-1 px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-jadwa-brown/30 focus:border-jadwa-brown placeholder:text-gray-400"
                  disabled={sendingMessage}
                />
                <button onClick={sendMessage} disabled={!userInput.trim() || sendingMessage} className="px-3 py-2 bg-jadwa-brown text-white rounded-lg hover:bg-jadwa-brown-dark transition-colors disabled:opacity-40" title="Send">
                  <Send size={16} />
                </button>
                <button onClick={continueDebate} disabled={sendingMessage} className="px-3 py-2 text-xs font-medium text-jadwa-brown bg-jadwa-brown/5 rounded-lg hover:bg-jadwa-brown/10 transition-colors disabled:opacity-40 whitespace-nowrap">
                  Next Round
                </button>
              </div>
            </div>
          )}

          {/* Demo footer */}
          {isDemo && visibleCount >= session.conversation.length && (
            <div className="border-t border-gray-200 p-3 text-center fade-in">
              <p className="text-[11px] text-gray-500 mb-2">This was a scripted demo. Start a live debate with real AI agents.</p>
              <div className="flex items-center justify-center gap-2">
                <button
                  onClick={startDemo}
                  className="inline-flex items-center gap-1.5 px-4 py-2 bg-white text-jadwa-brown border border-jadwa-brown/20 rounded-lg text-xs font-medium hover:bg-jadwa-brown/5 transition-colors"
                >
                  <RefreshCw size={12} />
                  Replay
                </button>
                <button
                  onClick={resetAll}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-jadwa-brown text-white rounded-lg text-xs font-medium hover:bg-jadwa-brown-dark transition-colors"
                >
                  <MessageSquare size={14} />
                  Start Live Debate
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* IC Memo section */}
      {isDone && !isDemo && !memo && (
        <button
          onClick={generateMemo}
          disabled={memoLoading}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-jadwa-brown/5 text-jadwa-brown border border-jadwa-brown/15 rounded-xl text-sm font-medium hover:bg-jadwa-brown/10 transition-colors disabled:opacity-50"
        >
          {memoLoading ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
          {memoLoading ? "Generating IC Memo..." : "Generate Investment Committee Memo"}
        </button>
      )}

      {memo && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileText size={14} className="text-jadwa-brown" />
              <span className="text-xs font-semibold text-gray-700">Investment Committee Memo</span>
            </div>
            <button onClick={() => setMemo(null)} className="text-gray-400 hover:text-gray-600"><X size={14} /></button>
          </div>
          <div className="px-5 py-4 prose prose-sm prose-gray max-w-none text-sm leading-relaxed [&_h1]:text-base [&_h1]:font-bold [&_h1]:mb-3 [&_h2]:text-sm [&_h2]:font-bold [&_h2]:mt-4 [&_h2]:mb-2 [&_p]:mb-2 [&_ul]:mb-2 [&_li]:mb-0.5">
            <ReactMarkdown>{memo}</ReactMarkdown>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between text-[10px] text-gray-400 px-1">
        <span>
          {session.conversation.length} messages
          {!isDemo && ` · ${session.total_tokens} tokens`}
          {!isDemo && (session.scenarios_applied?.length || 0) > 0 && ` · ${session.scenarios_applied.length} scenario${session.scenarios_applied.length > 1 ? "s" : ""}`}
        </span>
        {error && <span className="text-red-400">{error}</span>}
      </div>
    </div>
  );
}
