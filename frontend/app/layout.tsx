import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: "JadwaChat",
  description:
    "AI RAG-powered chat. Built for Jadwa Investment.",
  icons: { icon: "/favicon.ico" },
  themeColor: "#f5f0e8",
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
