"use client";

import { useEffect, useState } from "react";
import Image from "next/image";

interface SplashScreenProps {
  onFinished: () => void;
  /** Total duration in ms before the splash calls onFinished */
  duration?: number;
}

/**
 * Jadwa-branded splash screen with:
 *  - Warm desert gradient background
 *  - Animated sand waves flowing across the bottom
 *  - Logo that rises and blooms from the center
 *  - Floating golden particles (sand dust)
 *  - "JadwaChat" text that fades in
 *  - The whole screen fades out to reveal the app
 */
export default function SplashScreen({
  onFinished,
  duration = 3400,
}: SplashScreenProps) {
  const [phase, setPhase] = useState<"enter" | "hold" | "exit">("enter");

  useEffect(() => {
    // Phase 1: enter (logo + text animate in)
    const holdTimer = setTimeout(() => setPhase("hold"), 600);

    // Phase 2: start exit
    const exitTimer = setTimeout(() => setPhase("exit"), duration - 800);

    // Phase 3: notify parent to unmount
    const doneTimer = setTimeout(() => onFinished(), duration);

    return () => {
      clearTimeout(holdTimer);
      clearTimeout(exitTimer);
      clearTimeout(doneTimer);
    };
  }, [duration, onFinished]);

  return (
    <div
      className={`splash-overlay ${phase === "exit" ? "splash-fade-out" : ""}`}
    >
      {/* ── Animated sand waves (smooth cubic bezier curves) ── */}
      <div className="splash-waves">
        <svg
          className="splash-wave splash-wave-1"
          viewBox="0 0 1440 320"
          preserveAspectRatio="none"
        >
          <path
            d="M0,192 C240,120 480,260 720,200 S1200,100 1440,180 L1440,320 L0,320 Z"
            fill="rgba(139,115,85,0.12)"
          />
        </svg>
        <svg
          className="splash-wave splash-wave-2"
          viewBox="0 0 1440 320"
          preserveAspectRatio="none"
        >
          <path
            d="M0,220 C320,160 560,280 840,210 S1280,140 1440,200 L1440,320 L0,320 Z"
            fill="rgba(145,119,92,0.15)"
          />
        </svg>
        <svg
          className="splash-wave splash-wave-3"
          viewBox="0 0 1440 320"
          preserveAspectRatio="none"
        >
          <path
            d="M0,250 C200,200 440,290 720,240 S1100,180 1440,230 L1440,320 L0,320 Z"
            fill="rgba(107,88,64,0.10)"
          />
        </svg>
      </div>

      {/* ── Floating golden particles ──────────────────── */}
      <div className="splash-particles">
        {Array.from({ length: 30 }).map((_, i) => (
          <span
            key={i}
            className="splash-particle"
            style={{
              left: `${5 + Math.random() * 90}%`,
              animationDelay: `${Math.random() * 2}s`,
              animationDuration: `${2 + Math.random() * 2.5}s`,
              width: `${3 + Math.random() * 5}px`,
              height: `${3 + Math.random() * 5}px`,
              opacity: 0.5 + Math.random() * 0.5,
            }}
          />
        ))}
      </div>

      {/* ── Center content ─────────────────────────────── */}
      <div className="splash-center">
        {/* Glow ring behind the logo */}
        <div className="splash-glow" />

        {/* Logo */}
        <div className="splash-logo">
          <div className="w-[90px] h-[90px] sm:w-[120px] sm:h-[120px] rounded-[22%] overflow-hidden shadow-2xl">
            <Image
              src="/jadwa-logo.png"
              alt="Jadwa Investment"
              width={120}
              height={120}
              priority
              className="w-full h-full object-cover"
            />
          </div>
        </div>

        {/* Brand text */}
        <h1 className="splash-title">
          <span className="splash-title-jadwa">Jadwa</span>
          <span className="splash-title-chat">Chat</span>
        </h1>
        <p className="splash-subtitle">Intelligent Financial Assistant</p>
      </div>
    </div>
  );
}

