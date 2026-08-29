import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { cn } from "@ramanhub/ui";
import { ThemeProvider, ThemeToggle } from "@ramanhub/ui/theme";
import { Toaster } from "@ramanhub/ui/toast";

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

const geistSans = Geist({
  subsets: ["latin"],
  variable: "--font-geist-sans",
});
const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
});

export default function RootLayout(props: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={cn(
          "bg-background text-foreground min-h-screen font-sans antialiased",
          geistSans.variable,
          geistMono.variable,
        )}
      >
        <ThemeProvider>
          {props.children}
          <div className="absolute right-4 bottom-4">
            <ThemeToggle />
          </div>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
