import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: "JadwaChat — AI-Powered Investment Research",
  description:
    "Intelligent RAG-powered chat with quant signal engine, agent debate, and IC memo autopilot. Built for Jadwa Investment.",
  icons: { icon: "/favicon.ico", apple: "/jadwa-logo.png" },
  openGraph: {
    title: "JadwaChat — AI-Powered Investment Research",
    description:
      "Quant signals, multi-agent debate, and RAG chat for Saudi macro research.",
    url: "https://jadwa-chat.com",
    siteName: "JadwaChat",
    images: [{ url: "/jadwa-logo.png", width: 512, height: 512, alt: "JadwaChat" }],
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "JadwaChat — AI-Powered Investment Research",
    description:
      "Quant signals, multi-agent debate, and RAG chat for Saudi macro research.",
    images: ["/jadwa-logo.png"],
  },
  robots: { index: true, follow: true },
};

export const viewport = {
  themeColor: "#f5f0e8",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="h-screen overflow-hidden">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
