import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import {
  CheckCheck,
  EyeOff,
  GitCompare,
  HardDrive,
  Library,
  Lock,
  MessagesSquare,
  Microscope,
  ScrollText,
  Search,
  Share2,
  SlidersHorizontal,
  UploadCloud,
} from "lucide-react";

import { Badge } from "@ramanhub/ui/badge";
import { Button } from "@ramanhub/ui/button";
import { Card } from "@ramanhub/ui/card";

import { PROVIDERS } from "~/components/auth/providers";
import { MarketingFooter } from "./marketing-footer";
import { MarketingHeader } from "./marketing-header";
import { SpectrumHero } from "./spectrum-hero";

/**
 * The public landing page, served at `/about` and — via `proxy.ts` — at `/` for
 * visitors with no session cookie.
 *
 * A server component on purpose: no `"use client"`, no session query, no fetch.
 * The only client code on the page is the chart island. Copy is drawn from the
 * product thesis and principles in `raman-platform-architecture-v2.md`, and
 * every capability named below maps to a surface that actually ships — the page
 * should never promise something a new member cannot find.
 */

interface Problem {
  icon: LucideIcon;
  title: string;
  body: string;
}

const PROBLEMS: Problem[] = [
  {
    icon: HardDrive,
    title: "Data dies with the student",
    body: "A PhD ends, the student leaves, and four years of spectra leave with them — on a lab desktop nobody logs into any more. Nothing was wrong with the measurements. There was simply nowhere to put them.",
  },
  {
    icon: Search,
    title: "Peaks nobody can assign",
    body: "You have a band you cannot place. Someone three labs over placed the same one years ago and never wrote it up, because “I assigned a peak” is not a paper. That knowledge exists; it just has no address.",
  },
  {
    icon: SlidersHorizontal,
    title: "Processing you cannot reproduce",
    body: "“Baseline corrected and smoothed.” Which baseline? What window, what order, what version? Published spectra usually reach you as pictures of data rather than data, and the steps between are gone.",
  },
  {
    icon: EyeOff,
    title: "Negative results vanish",
    body: "The sample that showed nothing, the batch that failed, the reference that did not match — all real evidence, all unpublishable, all quietly deleted. Everyone then repeats the same measurement.",
  },
];

interface Capability {
  icon: LucideIcon;
  title: string;
  body: string;
}

const CAPABILITIES: Capability[] = [
  {
    icon: Share2,
    title: "Share your data — on your terms",
    body: "Upload real vendor files, messy headers and all. Everything stays private while you work on it. Publishing is a decision you make, per record, when you are ready.",
  },
  {
    icon: MessagesSquare,
    title: "Ask questions, post findings",
    body: "Bring the band you cannot assign, the artefact you keep seeing, the result that did not fit. Findings are threads attached to real records, so an answer points at data instead of memory.",
  },
  {
    icon: Library,
    title: "Match against a reference library",
    body: "Compare an unknown against a growing public corpus of openly licensed pure-compound references — plus a private reference library of your own that nobody else can see.",
  },
  {
    icon: Microscope,
    title: "Process it in the open",
    body: "A versioned toolbox that records its own work: every step, parameter and algorithm version travels with the result, so anyone can replay exactly what you did.",
  },
];

interface Step {
  icon: LucideIcon;
  title: string;
  body: string;
}

const STEPS: Step[] = [
  {
    icon: UploadCloud,
    title: "Upload",
    body: "Drop in the file your instrument actually wrote. Vendor parsers handle the formats they know; a guarded AI fallback reads the headers they do not.",
  },
  {
    icon: CheckCheck,
    title: "Confirm",
    body: "You review the parsed metadata before anything is recorded. The machine may suggest. It never decides for you.",
  },
  {
    icon: SlidersHorizontal,
    title: "Process",
    body: "Work through the transparent toolbox. The raw file stays untouched and recoverable; every step is written down as you go.",
  },
  {
    icon: ScrollText,
    title: "Publish",
    body: "Release a citable record with its provenance intact and its manuscript link genuinely verified — or keep it private indefinitely.",
  },
];

interface Commitment {
  icon: LucideIcon;
  text: string;
}

const COMMITMENTS: Commitment[] = [
  {
    icon: Lock,
    text: "Raw source files are immutable and recoverable. We never overwrite what your instrument produced.",
  },
  {
    icon: CheckCheck,
    text: "You confirm the metadata. AI may suggest — it never silently decides.",
  },
  {
    icon: GitCompare,
    text: "Every result we display traces back to its source data and the exact steps that produced it.",
  },
  {
    icon: EyeOff,
    text: "Private by default. Publishing is explicit, and it never destroys provenance.",
  },
  {
    icon: Search,
    text: "Search answers scientific questions. Social popularity never changes scientific ranking.",
  },
];

function SectionHeading(props: { eyebrow: string; title: string; lede?: string }) {
  return (
    <div className="max-w-2xl">
      <p className="text-primary text-xs font-semibold tracking-widest uppercase">
        {props.eyebrow}
      </p>
      <h2 className="mt-2 text-2xl font-bold tracking-tight sm:text-3xl">
        {props.title}
      </h2>
      {props.lede ? (
        <p className="text-muted-foreground mt-3 text-base leading-relaxed">
          {props.lede}
        </p>
      ) : null}
    </div>
  );
}

export function Landing() {
  return (
    <>
      <MarketingHeader />

      <main>
        {/* ---------------------------------------------------------------- */}
        {/* Hero                                                             */}
        {/* ---------------------------------------------------------------- */}
        <section className="mx-auto w-full max-w-5xl px-4 pt-14 pb-16 sm:pt-20">
          <Badge variant="secondary" className="mb-5">
            Open science for spectroscopy · early access
          </Badge>

          <h1 className="max-w-3xl text-3xl font-bold tracking-tight text-balance sm:text-5xl">
            Most Raman spectra never leave the instrument PC.
          </h1>

          <p className="text-muted-foreground mt-5 max-w-2xl text-base leading-relaxed sm:text-lg">
            Spectra Insight is an open commons for spectral data. Upload the
            imperfect files your instrument really produces, correct them in the
            open, ask the questions a manual cannot answer, and publish a citable
            record your field can actually reuse — instead of a picture of one.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Button asChild size="lg">
              <Link href="/login">Join the commons</Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/library">Browse the public library</Link>
            </Button>
          </div>

          <p className="text-muted-foreground mt-4 text-sm">
            Free, and open to any spectroscopist. Sign in with Google, GitHub or
            ORCID — or look around as a guest first.
          </p>

          <Card className="mt-12 gap-3 overflow-hidden p-4 sm:p-6">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-sm font-semibold tracking-tight">
                Acetaminophen powder · 785 nm
              </h2>
              <p className="text-muted-foreground font-mono text-xs">
                Horiba iHR320 · x50 · 1800 gr/mm · 3 × 15 s
              </p>
            </div>
            <SpectrumHero />
            <p className="text-muted-foreground text-xs">
              A real measurement, not an illustration — cropped to the
              fingerprint region and despiked, with those two steps written down.
              That is the whole idea.
            </p>
          </Card>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* The problem                                                      */}
        {/* ---------------------------------------------------------------- */}
        <section
          id="problem"
          className="zone-home border-border border-y py-16 sm:py-20"
        >
          <div className="mx-auto w-full max-w-5xl px-4">
            <SectionHeading
              eyebrow="Why this exists"
              title="Spectroscopy loses most of what it measures"
              lede="Not to fraud or carelessness — to the plain absence of anywhere to put a spectrum that is not a figure in a paper. Four ways that plays out:"
            />

            <div className="mt-10 grid gap-4 sm:grid-cols-2">
              {PROBLEMS.map((p) => (
                <Card key={p.title} className="gap-3 p-5">
                  <div className="flex items-center gap-2.5">
                    <span className="bg-secondary text-foreground/70 flex size-8 shrink-0 items-center justify-center rounded-lg">
                      <p.icon className="size-4" aria-hidden />
                    </span>
                    <h3 className="text-base font-semibold tracking-tight">
                      {p.title}
                    </h3>
                  </div>
                  <p className="text-muted-foreground text-sm leading-relaxed">
                    {p.body}
                  </p>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Capabilities                                                     */}
        {/* ---------------------------------------------------------------- */}
        <section id="capabilities" className="py-16 sm:py-20">
          <div className="mx-auto w-full max-w-5xl px-4">
            <SectionHeading
              eyebrow="What you can do here"
              title="Contribute what you already have"
              lede="You do not need a new project to take part. The spectra on your drive right now are the contribution."
            />

            <div className="mt-10 grid gap-4 sm:grid-cols-2">
              {CAPABILITIES.map((c) => (
                <Card key={c.title} className="gap-3 p-5">
                  <div className="flex items-center gap-2.5">
                    <span className="bg-primary/10 text-primary flex size-8 shrink-0 items-center justify-center rounded-lg">
                      <c.icon className="size-4" aria-hidden />
                    </span>
                    <h3 className="text-base font-semibold tracking-tight">
                      {c.title}
                    </h3>
                  </div>
                  <p className="text-muted-foreground text-sm leading-relaxed">
                    {c.body}
                  </p>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* How it works                                                     */}
        {/* ---------------------------------------------------------------- */}
        <section className="zone-mylab border-border border-y py-16 sm:py-20">
          <div className="mx-auto w-full max-w-5xl px-4">
            <SectionHeading
              eyebrow="How it works"
              title="From a messy vendor file to a citable record"
            />

            <ol className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map((s, i) => (
                <li key={s.title}>
                  <Card className="h-full gap-3 p-5">
                    <div className="flex items-center gap-2.5">
                      <span className="bg-primary text-primary-foreground flex size-8 shrink-0 items-center justify-center rounded-lg text-sm font-semibold">
                        {i + 1}
                      </span>
                      <h3 className="text-base font-semibold tracking-tight">
                        {s.title}
                      </h3>
                    </div>
                    <p className="text-muted-foreground text-sm leading-relaxed">
                      {s.body}
                    </p>
                  </Card>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Commitments                                                      */}
        {/* ---------------------------------------------------------------- */}
        <section className="py-16 sm:py-20">
          <div className="mx-auto w-full max-w-5xl px-4">
            <SectionHeading
              eyebrow="Our commitments"
              title="What we will not do to your data"
              lede="An open commons only works if the rules are stated up front and do not move. These are ours."
            />

            <ul className="mt-10 max-w-3xl space-y-3">
              {COMMITMENTS.map((c) => (
                <li
                  key={c.text}
                  className="border-border bg-card flex items-start gap-3 rounded-xl border p-4"
                >
                  <span className="text-primary mt-0.5 shrink-0">
                    <c.icon className="size-4" aria-hidden />
                  </span>
                  <p className="text-sm leading-relaxed">{c.text}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Closing CTA                                                      */}
        {/* ---------------------------------------------------------------- */}
        <section className="border-border border-t py-16 sm:py-20">
          <div className="mx-auto w-full max-w-2xl px-4 text-center">
            <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
              Your spectra are worth more than your hard drive
            </h2>
            <p className="text-muted-foreground mt-3 text-base leading-relaxed">
              Bring one file, one question, or one finding. That is enough to
              start.
            </p>

            <div className="mx-auto mt-8 max-w-sm space-y-2">
              {PROVIDERS.map((p) => (
                <Button
                  key={p.href}
                  asChild
                  variant="outline"
                  className="w-full"
                >
                  <a href={p.href}>{p.label}</a>
                </Button>
              ))}
              <Button asChild variant="ghost" className="w-full">
                <Link href="/login">Or look around as a guest</Link>
              </Button>
            </div>

            <p className="text-muted-foreground mt-8 text-xs leading-relaxed">
              Spectra Insight is in early access. Things are still being built,
              and we would rather tell you that than pretend otherwise. By
              continuing you agree to our{" "}
              <Link
                href="/terms"
                className="text-foreground focus-visible:ring-ring/50 rounded underline underline-offset-2 focus-visible:ring-[3px] focus-visible:outline-none"
              >
                Terms
              </Link>{" "}
              and{" "}
              <Link
                href="/privacy"
                className="text-foreground focus-visible:ring-ring/50 rounded underline underline-offset-2 focus-visible:ring-[3px] focus-visible:outline-none"
              >
                Privacy Policy
              </Link>
              .
            </p>
          </div>
        </section>
      </main>

      <MarketingFooter />
    </>
  );
}
