import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { cn } from "@ramanhub/ui";
import { ThemeProvider } from "@ramanhub/ui/theme";
import { Toaster } from "@ramanhub/ui/toast";

import { SITE_URL } from "~/lib/site-url";

import "~/app/styles.css";

const SITE_DESCRIPTION =
  "The reproducible workspace and trusted commons for spectral data — Raman first.";

/**
 * `metadataBase` is what lets per-route `generateMetadata` return relative
 * canonical/OG URLs and have Next resolve them absolutely; without it Next warns
 * and emits relative OG URLs, which most crawlers drop.
 *
 * Note there is deliberately no global `alternates.canonical` or
 * `openGraph.url`. Setting them here made every route declare the homepage as
 * its canonical — `/privacy` was emitting
 * `<link rel="canonical" href="https://raman.spectra-in.site"/>`, telling Google
 * it was a duplicate of `/`. With nothing set, each route self-canonicalizes,
 * which is correct everywhere except the marketing route, which sets its own.
 */
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Spectra Insight",
    template: "%s · Spectra Insight",
  },
  description: SITE_DESCRIPTION,
  openGraph: {
    type: "website",
    title: "Spectra Insight",
    description: SITE_DESCRIPTION,
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

/**
 * The root layout carries only what genuinely belongs to every document: the
 * fonts, the theme class on `<html>`, and the toaster. The application chrome
 * lives in `(app)/layout.tsx` so marketing routes can opt out of it.
 */
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
          {props.children}
          {/* Outside `Providers` deliberately — no QueryClient dependency, and
              it renders nothing until a toast fires. */}
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
