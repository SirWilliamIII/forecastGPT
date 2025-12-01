import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Providers } from "@/lib/providers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "BloombergGPT | Semantic Markets",
  description: "AI-powered crypto market forecasting with semantic analysis",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} min-h-screen bg-gray-950 text-white antialiased`}
      >
        <Providers>
          <nav className="border-b border-gray-800 bg-gray-900/50 backdrop-blur">
            <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4">
              <a href="/" className="flex items-center gap-2">
                <span className="text-xl font-bold text-white">
                  Bloomberg<span className="text-blue-500">GPT</span>
                </span>
              </a>
              <div className="flex gap-6">
                <a
                  href="/"
                  className="text-sm text-gray-400 transition-colors hover:text-white"
                >
                  Dashboard
                </a>
                <a
                  href="/events"
                  className="text-sm text-gray-400 transition-colors hover:text-white"
                >
                  Events
                </a>
              </div>
            </div>
          </nav>
          <main className="mx-auto max-w-7xl px-4 py-8">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
