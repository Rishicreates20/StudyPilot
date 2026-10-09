import type { Metadata, Viewport } from "next";
import {
  Geist_Mono,
  Inter,
  Noto_Sans_Devanagari,
  Noto_Sans_Oriya,
  Source_Serif_4,
} from "next/font/google";

import { SiteFooter } from "@/components/layout/site-footer";
import { SiteHeader } from "@/components/layout/site-header";
import { SkipLink } from "@/components/layout/skip-link";
import { ThemeProvider } from "@/components/layout/theme-provider";
import { siteDescription, siteName } from "@/lib/site";

import "./globals.css";

// Interface and reading faces. Devanagari and Odia are loaded as fallbacks: each font is split
// by unicode-range, so the browser only downloads them when a page actually contains those
// scripts (the product supports Hindi and Odia learning content).
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  variable: "--font-source-serif",
  display: "swap",
});
const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
  display: "swap",
  preload: false,
});
const devanagari = Noto_Sans_Devanagari({
  subsets: ["devanagari"],
  variable: "--font-devanagari",
  display: "swap",
  preload: false,
});
const oriya = Noto_Sans_Oriya({
  subsets: ["oriya"],
  variable: "--font-oriya",
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: { default: siteName, template: `%s · ${siteName}` },
  description: siteDescription,
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#faf9f6" },
    { media: "(prefers-color-scheme: dark)", color: "#101218" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  const fontVariables = [
    inter.variable,
    sourceSerif.variable,
    geistMono.variable,
    devanagari.variable,
    oriya.variable,
  ].join(" ");

  return (
    <html lang="en" className={fontVariables} suppressHydrationWarning>
      <body className="min-h-dvh">
        <ThemeProvider>
          <SkipLink />
          <div className="flex min-h-dvh flex-col">
            <SiteHeader />
            <main id="main-content" tabIndex={-1} className="flex-1 outline-none">
              {children}
            </main>
            <SiteFooter />
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
