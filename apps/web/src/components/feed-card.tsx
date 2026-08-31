import Link from "next/link";
import type { FeedItem } from "@ramanhub/api-client";

import { FeedCardMedia } from "./feed-card-media";

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
  const authorName = item.author?.display_name ?? item.author?.handle ?? "Someone";
  const authorHref = item.author?.handle ? `/u/${item.author.handle}` : null;
  const chip = metaChip(item);
  const hasMedia =
    item.kind === "finding" &&
    item.spectrum_count != null &&
    item.spectrum_count > 0;

  return (
    <article className="border-border bg-card hover:border-primary/40 rounded-xl border p-4 transition-colors">
      <div className="text-muted-foreground flex items-center gap-2 text-xs">
        <span className="bg-primary/10 text-primary inline-flex size-6 items-center justify-center rounded-full text-[0.6rem] font-semibold">
          {initials(authorName)}
        </span>
        {authorHref ? (
          <Link href={authorHref} className="hover:text-foreground font-medium">
            {authorName}
          </Link>
        ) : (
          <span className="font-medium">{authorName}</span>
        )}
        <span>·</span>
        <span>{timeAgo(item.published_at)}</span>
        <span className="ml-auto uppercase tracking-wide">
          {item.kind === "finding" ? "finding" : "spectrum"}
        </span>
      </div>

      <h2 className="mt-2 text-base font-semibold">
        <Link href={href} className="hover:text-primary">
          {item.title ?? "Untitled"}
        </Link>
      </h2>
      {item.summary && (
        <p className="text-muted-foreground mt-1 line-clamp-3 text-sm">
          {item.summary}
        </p>
      )}

      {hasMedia && <FeedCardMedia findingId={item.id} />}

      <div className="text-muted-foreground mt-3 flex flex-wrap items-center gap-3 text-xs">
        <span>▲ {item.vote_count}</span>
        <span>💬 {item.comment_count}</span>
        {chip && (
          <span className="bg-muted rounded px-1.5 py-0.5 font-medium">
            {chip}
          </span>
        )}
        {item.spectrum_count != null && item.spectrum_count > 0 && (
          <span>{item.spectrum_count} spectra</span>
        )}
        {item.accession && <span className="font-mono">{item.accession}</span>}
        {item.doi && (
          <span className="text-primary">DOI-linked</span>
        )}
        {item.tags?.slice(0, 4).map((t) => (
          <span key={t} className="bg-muted rounded px-1.5 py-0.5">
            #{t}
          </span>
        ))}
      </div>
    </article>
  );
}
