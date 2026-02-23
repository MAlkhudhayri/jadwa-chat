"use client";

interface RadarPoint {
  label: string;
  score: number; // -100 to +100
}

interface RadarChartProps {
  points: RadarPoint[];
  size?: number;
}

export default function RadarChart({ points, size = 220 }: RadarChartProps) {
  if (points.length < 3) return null;

  const cx = size / 2;
  const cy = size / 2;
  const maxR = size / 2 - 30;
  const n = points.length;
  const angleStep = (2 * Math.PI) / n;

  const normalise = (score: number) => (score + 100) / 200; // 0 to 1

  // Grid rings
  const rings = [0.25, 0.5, 0.75, 1.0];

  // Compute polygon vertices
  const vertices = points.map((p, i) => {
    const angle = -Math.PI / 2 + i * angleStep;
    const r = normalise(p.score) * maxR;
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
    };
  });

  const polygonPath = vertices.map((v, i) => `${i === 0 ? "M" : "L"} ${v.x} ${v.y}`).join(" ") + " Z";

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="hidden sm:block">
      {/* Grid rings */}
      {rings.map((r, i) => (
        <polygon
          key={i}
          points={Array.from({ length: n }, (_, j) => {
            const angle = -Math.PI / 2 + j * angleStep;
            const px = cx + r * maxR * Math.cos(angle);
            const py = cy + r * maxR * Math.sin(angle);
            return `${px},${py}`;
          }).join(" ")}
          fill="none"
          stroke="#e5e7eb"
          strokeWidth={1}
        />
      ))}

      {/* Axis lines */}
      {points.map((_, i) => {
        const angle = -Math.PI / 2 + i * angleStep;
        const x = cx + maxR * Math.cos(angle);
        const y = cy + maxR * Math.sin(angle);
        return (
          <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="#e5e7eb" strokeWidth={1} />
        );
      })}

      {/* Data polygon */}
      <path d={polygonPath} fill="rgba(139,115,85,0.15)" stroke="#8B7355" strokeWidth={2} />

      {/* Data points */}
      {vertices.map((v, i) => (
        <circle
          key={i}
          cx={v.x}
          cy={v.y}
          r={4}
          fill={points[i].score > 0 ? "#22c55e" : points[i].score < -20 ? "#ef4444" : "#eab308"}
          stroke="white"
          strokeWidth={2}
        />
      ))}

      {/* Labels */}
      {points.map((p, i) => {
        const angle = -Math.PI / 2 + i * angleStep;
        const labelR = maxR + 18;
        const x = cx + labelR * Math.cos(angle);
        const y = cy + labelR * Math.sin(angle);
        return (
          <text
            key={i}
            x={x}
            y={y}
            textAnchor="middle"
            dominantBaseline="middle"
            className="fill-gray-600 text-[10px] font-medium"
          >
            {p.label}
          </text>
        );
      })}
    </svg>
  );
}



