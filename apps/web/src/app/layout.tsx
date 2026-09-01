import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { cn } from "@ramanhub/ui";
import { ThemeProvider, ThemeToggle } from "@ramanhub/ui/theme";
import { Toaster } from "@ramanhub/ui/toast";

import { Providers } from "~/app/providers";
import { AppShell } from "~/components/app-shell";

import "~/app/styles.css";

export const metadata: Metadata = {
  title: "Spectra Insight",
  description:
    "The reproducible workspace and trusted commons for spectral data — Raman first.",
  openGraph: {
    title: "Spectra Insight",
    description:
      "The reproducible workspace and trusted commons for spectral data — Raman first.",
    url: "https://spectra-in.site",
    siteName: "Spectra Insight",
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
