import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { cn } from "@ramanhub/ui";
import { ThemeProvider, ThemeToggle } from "@ramanhub/ui/theme";
import { Toaster } from "@ramanhub/ui/toast";

import { Providers } from "~/app/providers";
import { AppShell } from "~/components/app-shell";
import { env } from "~/env";

import "~/app/styles.css";

const SITE_DESCRIPTION =
  "The reproducible workspace and trusted commons for spectral data — Raman first.";

/**
 * The Raman application's own origin (ADR-014: `spectra-in.site` is the product
 * site, `raman.spectra-in.site` is this app). `metadataBase` is what lets
 * per-route `generateMetadata` return relative canonical/OG URLs and have Next
 * resolve them absolutely; without it Next warns and emits relative OG URLs,
 * which most crawlers drop.
 *
 * `env.SITE_URL` is `undefined` when env validation is skipped (CI builds), so
 * fall back to the canonical origin — `new URL(undefined)` would crash the build.
 */
const SITE_URL = env.SITE_URL ?? "https://raman.spectra-in.site";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Spectra Insight",
    template: "%s · Spectra Insight",
  },
  description: SITE_DESCRIPTION,
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    title: "Spectra Insight",
    description: SITE_DESCRIPTION,
    url: SITE_URL,
    siteName: "Spectra Insight",
  },
  twitter: {
    card: "summary_large_image",
    title: "Spectra Insight",
    description: SITE_DESCRIPTION,
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "white" },
    { media: "(prefers-color-scheme: dark)", color: "black" },
  ],
};

const fontSans = Inter({
  subsets: ["latin"],
  variable: "--font-sans-src",
});
const fontMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono-src",
});

export default function RootLayout(props: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={cn(
          "bg-background text-foreground min-h-screen font-sans antialiased",
          fontSans.variable,
          fontMono.variable,
        )}
      >
        <ThemeProvider>
          <Providers>
            <AppShell>{props.children}</AppShell>
          </Providers>
          <div className="fixed bottom-[calc(4.5rem+env(safe-area-inset-bottom))] left-4 z-30 md:right-4 md:bottom-4 md:left-auto">
            <ThemeToggle />
          </div>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
