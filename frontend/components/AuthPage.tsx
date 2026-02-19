"use client";

import React, { useState } from "react";
import Image from "next/image";
import { useAuth } from "@/lib/auth";

export default function AuthPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        if (!fullName.trim()) {
          setError("Full name is required");
          setLoading(false);
          return;
        }
        await register(email, password, fullName);
      }
    } catch (err: any) {
      setError(err.message || "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#faf8f5] px-4 py-8 sm:py-0">
      <div className="w-full max-w-md">
        {/* Logo & title */}
        <div className="flex flex-col items-center mb-6 sm:mb-8">
          <div className="w-16 h-16 sm:w-20 sm:h-20 rounded-[22%] overflow-hidden mb-3 sm:mb-4 shadow-lg">
            <Image
              src="/jadwa-logo.png"
              alt="Jadwa"
              width={80}
              height={80}
              className="w-full h-full object-cover"
              priority
            />
          </div>
          <h1 className="text-2xl font-bold text-[#2c1810]">JadwaChat</h1>
          <p className="text-sm text-[#8b7355] mt-1">
            {mode === "login" ? "Sign in to continue" : "Create your account"}
          </p>
        </div>

        {/* Form card */}
        <div className="bg-white rounded-2xl shadow-xl p-5 sm:p-6 border border-[#e8dfd3]">
          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === "register" && (
              <div>
                <label className="block text-sm font-medium text-[#4a3728] mb-1">
                  Full Name
                </label>
                <input
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl border border-[#d4c5b0] bg-[#faf8f5]
                             text-[#2c1810] placeholder-[#b8a58c]
                             focus:outline-none focus:ring-2 focus:ring-[#8b7355]/40 focus:border-[#8b7355]
                             transition-all"
                  placeholder="Mohammed Alkhudhayri"
                  autoComplete="name"
                />
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-[#4a3728] mb-1">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-2.5 rounded-xl border border-[#d4c5b0] bg-[#faf8f5]
                           text-[#2c1810] placeholder-[#b8a58c]
                           focus:outline-none focus:ring-2 focus:ring-[#8b7355]/40 focus:border-[#8b7355]
                           transition-all"
                placeholder="you@jadwa.com"
                autoComplete="email"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-[#4a3728] mb-1">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-2.5 rounded-xl border border-[#d4c5b0] bg-[#faf8f5]
                           text-[#2c1810] placeholder-[#b8a58c]
                           focus:outline-none focus:ring-2 focus:ring-[#8b7355]/40 focus:border-[#8b7355]
                           transition-all"
                placeholder="••••••••"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                required
                minLength={6}
              />
            </div>

            {error && (
              <div className="p-3 rounded-xl bg-red-50 border border-red-200">
                <p className="text-sm text-red-700">{error}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-xl font-semibold text-white
                         bg-gradient-to-r from-[#6b4c3b] to-[#8b7355]
                         hover:from-[#5a3f30] hover:to-[#7a6449]
                         disabled:opacity-50 disabled:cursor-not-allowed
                         transition-all shadow-md"
            >
              {loading
                ? "Please wait..."
                : mode === "login"
                ? "Sign In"
                : "Create Account"}
            </button>
          </form>

          {/* Toggle login/register */}
          <div className="mt-5 text-center">
            <p className="text-sm text-[#8b7355]">
              {mode === "login" ? "Don't have an account?" : "Already have an account?"}{" "}
              <button
                onClick={() => {
                  setMode(mode === "login" ? "register" : "login");
                  setError("");
                }}
                className="font-semibold text-[#6b4c3b] hover:text-[#4a3728] underline
                           underline-offset-2 transition-colors"
              >
                {mode === "login" ? "Sign up" : "Sign in"}
              </button>
            </p>
          </div>
        </div>

        {/* Footer */}
        <p className="text-center text-xs text-[#b8a58c] mt-6">
          Built for Jadwa Investment
        </p>
      </div>
    </div>
  );
}

