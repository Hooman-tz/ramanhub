import { ExternalLink } from "lucide-react";

import type { PublicationMeta } from "@ramanhub/api-client";
import { Badge } from "@ramanhub/ui/badge";
import { Card, CardContent } from "@ramanhub/ui/card";

/** Deterministic 0–360 hue from a string — stable cover gradient per journal. */
function hueFrom(seed: string): number {
  let h = 0;
  for (let i = 0; i < seed.length; i++) {
    h = (h * 31 + seed.charCodeAt(i)) % 360;
  }
  return h;
}

function GeneratedCover({ journal }: { journal: string }) {
  const h = hueFrom(journal);
  return (
    <div
      className="flex h-[120px] w-[90px] shrink-0 items-end overflow-hidden rounded-md p-1.5"
      style={{
        backgroundImage: `linear-gradient(150deg, oklch(0.62 0.14 ${h}), oklch(0.42 0.13 ${(h + 40) % 360}))`,
      }}
    >
      <span className="line-clamp-4 text-[0.6rem] leading-tight font-semibold text-white/95">
        {journal}
      </span>
    </div>
  );
}

export function JournalCard({ meta }: { meta: PublicationMeta | null }) {
  if (!meta?.doi) return null;

  const journal = meta.journal ?? "Journal";
  const q = meta.quartile ?? null;

  return (
    <Card className="mt-6 py-4">
      <CardContent className="flex gap-4">
        {meta.cover_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={meta.cover_url}
            alt={journal}
            className="h-[120px] w-[90px] shrink-0 rounded-md object-cover"
          />
        ) : (
          <GeneratedCover journal={journal} />
        )}

        <div className="min-w-0 flex-1 text-sm">
          {meta.title && (
            <p className="text-foreground font-medium" title={meta.title}>
              {meta.title}
            </p>
          )}
          <p className="text-foreground/70 mt-0.5">
            {journal}
            {meta.year ? ` · ${meta.year}` : ""}
          </p>

          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            {q && (
              <Badge
                variant={q.toUpperCase() === "Q1" ? "success" : "secondary"}
              >
                {q.toUpperCase()} journal
              </Badge>
            )}
            {meta.sjr != null && (
              <span className="text-foreground/70">SJR {meta.sjr}</span>
            )}
            {meta.citations != null && (
              <span className="text-foreground/70">
                {meta.citations} citations
              </span>
            )}
          </div>

          <a
            href={`https://doi.org/${meta.doi}`}
            target="_blank"
            rel="noreferrer"
            className="text-primary focus-visible:ring-ring/50 mt-2 inline-flex items-center gap-1 rounded text-xs hover:underline focus-visible:ring-[3px] focus-visible:outline-none"
          >
            View paper
            <ExternalLink className="size-3.5" aria-hidden />
          </a>
        </div>
      </CardContent>
    </Card>
  );
}
