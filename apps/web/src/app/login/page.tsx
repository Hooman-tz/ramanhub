"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { startGuestSession } from "@ramanhub/api-client";
import { Button } from "@ramanhub/ui/button";

const PROVIDERS = [
  { label: "Continue with Google", href: "/api/auth/login" },
  { label: "Continue with GitHub", href: "/api/auth/github/login" },
  { label: "Continue with ORCID", href: "/api/auth/orcid/login" },
];

function LoginCard() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const rawNext = params.get("next");
  const next = rawNext?.startsWith("/") ? rawNext : "/";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function continueAsGuest() {
    setBusy(true);
    setError(null);
    try {
      await startGuestSession();
      await qc.invalidateQueries({ queryKey: ["session"] });
      router.push(next);
    } catch {
      setError("Could not start a guest session — try again.");
      setBusy(false);
    }
  }

  return (
    <div className="border-border bg-card rounded-2xl border p-6">
      <h1 className="text-xl font-bold tracking-tight">
        Sign in to Spectra<span className="text-primary">Insight</span>
      </h1>
      <p className="text-foreground/80 mt-1 text-sm">
        Use an academic identity to publish, vote, and comment.
      </p>

      <div className="mt-6 space-y-2">
        {PROVIDERS.map((p) => (
          <Button key={p.href} asChild variant="outline" className="w-full">
            <a href={p.href}>{p.label}</a>
          </Button>
        ))}
      </div>

      <div className="border-border my-5 border-t" />

      <Button
        variant="ghost"
        className="w-full"
        disabled={busy}
        onClick={continueAsGuest}
      >
        {busy ? "One moment…" : "Continue as guest"}
      </Button>
      {error && (
        <p className="text-destructive mt-2 text-xs" role="alert">
          {error}
        </p>
      )}

      <p className="text-foreground/70 mt-5 text-center text-xs">
        By continuing you agree to our{" "}
        <a
          href="/terms"
          className="text-foreground focus-visible:ring-ring/50 rounded underline underline-offset-2 focus-visible:ring-[3px] focus-visible:outline-none"
        >
          Terms
        </a>{" "}
        and{" "}
        <a
          href="/privacy"
          className="text-foreground focus-visible:ring-ring/50 rounded underline underline-offset-2 focus-visible:ring-[3px] focus-visible:outline-none"
        >
          Privacy Policy
        </a>
        .
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center px-4 py-12">
      <Suspense fallback={null}>
        <LoginCard />
      </Suspense>
    </main>
  );
}
