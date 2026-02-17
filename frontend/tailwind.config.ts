import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        jadwa: {
          navy: "#1B2A4A",
          "navy-light": "#243560",
          "navy-dark": "#111D35",
          gold: "#C9A84C",
          "gold-light": "#D4BA6A",
          "gold-dark": "#B08E30",
          slate: "#64748B",
          surface: "#F8FAFC",
          border: "#E2E8F0",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      animation: {
        "pulse-dot": "pulse-dot 1.5s infinite",
      },
      keyframes: {
        "pulse-dot": {
          "0%, 100%": { opacity: "0.3" },
          "50%": { opacity: "1" },
        },
      },
    },
  },
  plugins: [],
};

export default config;

