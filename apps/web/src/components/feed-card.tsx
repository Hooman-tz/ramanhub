import Link from "next/link";
import { ArrowBigUp, Link2, MessageSquare, Waves } from "lucide-react";

import type { FeedItem } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";

import { FeedCardMedia, FeedCardSpectrum } from "./feed-card-media";

function initials(name: string | null): string {
  if (!name) return "?";
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  const units: [number, string][] = [
    [60, "s"],
    [60, "m"],
    [24, "h"],
    [7, "d"],
    [4.35, "w"],
    [12, "mo"],
    [Number.POSITIVE_INFINITY, "y"],
  ];
  let v = secs;
  for (const [step, label] of units) {
    if (v < step) return `${Math.max(1, Math.floor(v))}${label} ago`;
    v /= step;
  }
  return "";
}

const AVATAR_PALETTE = [
  "#0d6b6e",
  "#b45309",
  "#1e3a5f",
  "#6d28d9",
  "#44403c",
] as const;

/** Deterministic warm accent for an author avatar, keyed off their id/handle. */
function avatarAccent(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[h % AVATAR_PALETTE.length] ?? AVATAR_PALETTE[0];
}

export function FeedCard({ item }: { item: FeedItem }) {
  const href =
    item.kind === "finding" ? `/findings/${item.id}` : `/spectra/${item.id}`;
  const authorName =
    item.author?.display_name ?? item.author?.handle ?? "Someone";
  const authorHref = item.author?.handle ? `/u/${item.author.handle}` : null;
  const accent = avatarAccent(
    item.author?.id ?? item.author?.handle ?? item.id,
  );
  const hasFindingMedia =
    item.kind === "finding" &&
    item.spectrum_count != null &&
    item.spectrum_count > 0;
  const galleryMeta = [
    item.material_type?.toUpperCase(),
    item.snr != null ? `SNR ${Math.round(item.snr)}` : null,
    item.spectrum_count ? `${item.spectrum_count} spectra` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <article className="border-border bg-card overflow-hidden rounded-2xl border shadow-sm">
      {/* Author header */}
      <div className="border-border/60 flex items-center gap-3 border-b px-5 py-4">
        <span
          className="flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
          style={{
            background: `linear-gradient(135deg, ${accent}cc, ${accent})`,
          }}
        >
          {initials(authorName)}
        </span>
        <div className="min-w-0 flex-1">
          {authorHref ? (
            <Link
              href={authorHref}
              className="hover:text-primary focus-visible:ring-ring/50 rounded text-sm font-semibold transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
            >
              {authorName}
            </Link>
          ) : (
            <span className="text-sm font-semibold">{authorName}</span>
          )}
          <div className="text-muted-foreground text-xs">
            {item.author?.handle ? `@${item.author.handle}` : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="border-border bg-muted text-muted-foreground rounded-full border px-2 py-0.5 text-[10px] tracking-wide uppercase">
            {item.kind}
          </span>
          <span className="text-muted-foreground text-xs">
            {timeAgo(item.published_at)}
          </span>
        </div>
      </div>

      {/* Title + summary */}
      <div className="px-5 pt-4 pb-3">
        <h2 className="text-sm leading-snug font-semibold tracking-tight">
          <Link
            href={href}
            className="hover:text-primary focus-visible:ring-ring/50 rounded transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
          >
            {item.title ?? "Untitled"}
          </Link>
        </h2>
        {item.summary && (
          <p className="text-muted-foreground mt-2 line-clamp-3 text-xs leading-relaxed">
            {item.summary}
          </p>
        )}
      </div>

      {/* Gallery */}
      {(hasFindingMedia || item.kind === "spectrum") && (
        <div className="px-5 pb-4">
          <div className="border-border bg-secondary/40 overflow-hidden rounded-xl border">
            <div className="border-border bg-muted/30 flex items-center justify-between border-b px-3 py-2">
              <span className="text-foreground font-mono text-[11px] font-medium">
                {item.kind === "finding" ? "Mean ± SD overlay" : "Raw spectrum"}
              </span>
              {galleryMeta && (
                <span className="text-muted-foreground font-mono text-[10px]">
                  {galleryMeta}
                </span>
              )}
            </div>
            {hasFindingMedia && <FeedCardMedia findingId={item.id} bare />}
            {item.kind === "spectrum" && (
              <FeedCardSpectrum spectrumId={item.id} bare />
            )}
          </div>
        </div>
      )}

      {/* Tags */}
      {item.tags && item.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-5 pb-3">
          {item.tags.slice(0, 5).map((t) => (
            <span
              key={t}
              className="border-border bg-muted text-muted-foreground rounded-full border px-2 py-0.5 text-[10px]"
            >
              #{t}
            </span>
          ))}
        </div>
      )}

      {/* Engagement row */}
      <div className="border-border/60 flex items-center gap-1 border-t px-3 py-3 sm:px-5">
        <span className="text-muted-foreground inline-flex items-center gap-1.5 rounded-xl px-2.5 py-2 text-sm font-medium">
          <ArrowBigUp className="size-4.5" aria-hidden />
          {item.vote_count}
          <span className="sr-only">votes</span>
        </span>
        <span className="text-muted-foreground inline-flex items-center gap-1.5 rounded-xl px-2.5 py-2 text-sm font-medium">
          <MessageSquare className="size-4" aria-hidden />
          {item.comment_count}
          <span className="sr-only">comments</span>
        </span>
        {item.doi && (
          <span className="text-primary inline-flex items-center gap-1.5 rounded-xl px-2.5 py-2 text-sm font-medium">
            <Link2 className="size-4" aria-hidden />
            <span className="hidden sm:inline">DOI</span>
          </span>
        )}

        <div className="flex-1" />

        {item.accession && (
          <span className="text-muted-foreground mr-1 hidden font-mono text-[11px] sm:inline">
            {item.accession}
          </span>
        )}
        <Link
          href={href}
          className={cn(
            "bg-primary text-primary-foreground focus-visible:ring-ring/50 inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold shadow-sm transition-opacity hover:opacity-90 focus-visible:ring-[3px] focus-visible:outline-none active:scale-95 motion-reduce:transition-none motion-reduce:active:scale-100",
          )}
        >
          <Waves className="size-4" aria-hidden />
          {item.kind === "finding" ? "Open finding" : "Open spectrum"}
        </Link>
      </div>
    </article>
  );
}
