"use client";

interface ScoreGaugeProps {
  score: number; // -100 to +100
  direction: string; // improving | stable | deteriorating
  label?: string;
  size?: "sm" | "md" | "lg";
}

export default function ScoreGauge({
  score,
  direction,
  label,
  size = "md",
}: ScoreGaugeProps) {
  // Map score (-100 to +100) → angle (180° to 0°) for semicircle
  const normalised = Math.max(-100, Math.min(100, score));
  const angle = 180 - ((normalised + 100) / 200) * 180;
  const radians = (angle * Math.PI) / 180;

  const dims = { sm: 100, md: 160, lg: 220 }[size];
  const stroke = { sm: 8, md: 12, lg: 16 }[size];
  const radius = (dims - stroke) / 2;
  const cx = dims / 2;
  const cy = dims / 2 + 10;

  // Needle endpoint
  const needleLen = radius - 10;
  const nx = cx + needleLen * Math.cos(radians);
  const ny = cy - needleLen * Math.sin(radians);

  // Score color
  const getColor = () => {
    if (normalised > 30) return "#22c55e"; // green
    if (normalised > 0) return "#84cc16"; // lime
    if (normalised > -30) return "#eab308"; // yellow
    if (normalised > -60) return "#f97316"; // orange
    return "#ef4444"; // red
  };

  const directionIcon =
    direction === "improving" ? "↑" : direction === "deteriorating" ? "↓" : "→";
  const directionColor =
    direction === "improving"
      ? "text-green-500"
      : direction === "deteriorating"
      ? "text-red-500"
      : "text-gray-400";

  const fontSize = { sm: "text-lg", md: "text-2xl", lg: "text-4xl" }[size];
  const subSize = { sm: "text-[10px]", md: "text-xs", lg: "text-sm" }[size];

  return (
    <div className="flex flex-col items-center">
      <svg width={dims} height={dims / 2 + 30} viewBox={`0 0 ${dims} ${dims / 2 + 30}`}>
        {/* Background arc */}
        <path
          d={`M ${cx - radius} ${cy} A ${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`}
          fill="none"
          stroke="#e5e7eb"
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        {/* Colored segments */}
        {[
          { start: 180, end: 144, color: "#ef4444" },
          { start: 144, end: 108, color: "#f97316" },
          { start: 108, end: 72, color: "#eab308" },
          { start: 72, end: 36, color: "#84cc16" },
          { start: 36, end: 0, color: "#22c55e" },
        ].map(({ start, end, color }, i) => {
          const s = (start * Math.PI) / 180;
          const e = (end * Math.PI) / 180;
          const x1 = cx + radius * Math.cos(s);
          const y1 = cy - radius * Math.sin(s);
          const x2 = cx + radius * Math.cos(e);
          const y2 = cy - radius * Math.sin(e);
          return (
            <path
              key={i}
              d={`M ${x1} ${y1} A ${radius} ${radius} 0 0 1 ${x2} ${y2}`}
              fill="none"
              stroke={color}
              strokeWidth={stroke}
              strokeLinecap="round"
              opacity={0.25}
            />
          );
        })}
        {/* Needle */}
        <line
          x1={cx}
          y1={cy}
          x2={nx}
          y2={ny}
          stroke={getColor()}
          strokeWidth={3}
          strokeLinecap="round"
        />
        <circle cx={cx} cy={cy} r={5} fill={getColor()} />
      </svg>
      <div className="flex flex-col items-center -mt-2">
        <span className={`font-bold ${fontSize}`} style={{ color: getColor() }}>
          {normalised > 0 ? "+" : ""}
          {normalised.toFixed(1)}
        </span>
        <span className={`${directionColor} ${subSize} font-medium mt-0.5`}>
          {direction} {directionIcon}
        </span>
        {label && (
          <span className={`text-gray-500 ${subSize} mt-0.5`}>{label}</span>
        )}
      </div>
    </div>
  );
}



