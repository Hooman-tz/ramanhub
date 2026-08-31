import Link from "next/link";
import { ArrowBigUp, LineChart, Link2, MessageSquare } from "lucide-react";

import type { FeedItem } from "@ramanhub/api-client";

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
    if (v < step) return `${Math.max(1, Math.floor(v))}${label}`;
    v /= step;
  }
  return "";
}

function metaChip(item: FeedItem): string | null {
  const parts: string[] = [];
  if (item.material_type) parts.push(item.material_type.toUpperCase());
  if (item.snr != null) parts.push(`SNR ${Math.round(item.snr)}`);
  return parts.length ? parts.join(" · ") : null;
}

export function FeedCard({ item }: { item: FeedItem }) {
  const href =
    item.kind === "finding" ? `/findings/${item.id}` : `/spectra/${item.id}`;
  const authorName =
    item.author?.display_name ?? item.author?.handle ?? "Someone";
  const authorHref = item.author?.handle ? `/u/${item.author.handle}` : null;
  const chip = metaChip(item);
  const hasFindingMedia =
    item.kind === "finding" &&
    item.spectrum_count != null &&
    item.spectrum_count > 0;

  return (
    <article className="border-border bg-card hover:border-primary/40 rounded-xl border p-5 shadow-sm transition-shadow hover:shadow-md motion-reduce:transition-none">
      <div className="text-foreground/70 flex items-center gap-2 text-xs">
        <span className="bg-primary/10 text-primary inline-flex size-6 items-center justify-center rounded-full text-[0.65rem] font-semibold">
          {initials(authorName)}
        </span>
        {authorHref ? (
          <Link
            href={authorHref}
            className="text-foreground hover:text-primary focus-visible:ring-ring/50 rounded font-medium transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
          >
            {authorName}
          </Link>
        ) : (
          <span className="text-foreground font-medium">{authorName}</span>
        )}
        <span aria-hidden>·</span>
        <span>{timeAgo(item.published_at)}</span>
        <span className="text-foreground/60 ml-auto tracking-wide uppercase">
          {item.kind === "finding" ? "finding" : "spectrum"}
        </span>
      </div>

      <h2 className="mt-3 text-lg leading-snug font-semibold tracking-tight">
        <Link
          href={href}
          className="hover:text-primary focus-visible:ring-ring/50 rounded transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
        >
          {item.title ?? "Untitled"}
        </Link>
      </h2>
      {item.summary && (
        <p className="text-foreground/80 mt-1.5 line-clamp-3 text-sm leading-relaxed">
          {item.summary}
        </p>
      )}

      {hasFindingMedia && <FeedCardMedia findingId={item.id} />}
      {item.kind === "spectrum" && <FeedCardSpectrum spectrumId={item.id} />}

      <div className="text-foreground/70 mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
        <span className="inline-flex items-center gap-1">
          <ArrowBigUp className="size-4" aria-hidden />
          <span>{item.vote_count}</span>
          <span className="sr-only">votes</span>
        </span>
        <span className="inline-flex items-center gap-1">
          <MessageSquare className="size-3.5" aria-hidden />
          <span>{item.comment_count}</span>
          <span className="sr-only">comments</span>
        </span>
        {item.spectrum_count != null && item.spectrum_count > 0 && (
          <span className="inline-flex items-center gap-1">
            <LineChart className="size-3.5" aria-hidden />
            <span>{item.spectrum_count} spectra</span>
          </span>
        )}
        {chip && (
          <span className="bg-muted text-foreground/80 rounded px-1.5 py-0.5 font-medium">
            {chip}
          </span>
        )}
        {item.accession && (
          <span className="text-foreground/70 font-mono">{item.accession}</span>
        )}
        {item.doi && (
          <span className="text-primary inline-flex items-center gap-1">
            <Link2 className="size-3.5" aria-hidden />
            DOI-linked
          </span>
        )}
        {item.tags?.slice(0, 4).map((t) => (
          <span
            key={t}
            className="bg-muted text-foreground/80 rounded px-1.5 py-0.5"
          >
            #{t}
          </span>
        ))}
      </div>
    </article>
  );
}
