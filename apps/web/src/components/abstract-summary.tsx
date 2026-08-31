"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { AiSummary, PublicationMeta } from "@ramanhub/api-client";
import { enrichFinding, isApiError } from "@ramanhub/api-client";
import { Badge } from "@ramanhub/ui/badge";
import { Button } from "@ramanhub/ui/button";

function SummaryBlock({
  summary,
  abstractRaw,
}: {
  summary: AiSummary;
  abstractRaw?: string | null;
}) {
  return (
    <div className="mt-6">
      <h2 className="text-base font-semibold tracking-tight">Summary</h2>
      <p className="text-foreground/90 mt-2 text-sm leading-relaxed">
        {summary.summary}
      </p>
      {summary.keywords.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {summary.keywords.map((k) => (
            <Badge key={k} variant="secondary">
              {k}
            </Badge>
          ))}
        </div>
      )}
      {abstractRaw && (
        <details className="mt-3 text-sm">
          <summary className="text-foreground/70 hover:text-foreground focus-visible:ring-ring/50 -m-1 w-fit cursor-pointer rounded-md p-1 transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none">
            Original abstract
          </summary>
          <p className="text-foreground/80 mt-2 leading-relaxed whitespace-pre-wrap">
            {abstractRaw}
          </p>
        </details>
      )}
      <p className="text-foreground/60 mt-2 text-xs">AI-generated summary.</p>
    </div>
  );
}

export function AbstractSummary({
  meta,
  findingId,
  isOwner,
}: {
  meta: PublicationMeta | null;
  findingId: string;
  isOwner: boolean;
}) {
  const qc = useQueryClient();
  const [result, setResult] = useState<AiSummary | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => enrichFinding(findingId),
    onSuccess: (res) => {
      if (res.enriched && res.ai_summary) {
        setResult(res.ai_summary);
        setNote(null);
        void qc.invalidateQueries({ queryKey: ["finding", findingId] });
      } else if (res.reason === "llm_not_configured") {
        setNote("AI summariser not configured.");
      } else {
        setNote("Could not generate a summary right now.");
      }
    },
    onError: (e) =>
      setNote(
        isApiError(e) ? e.message : "Could not generate a summary right now.",
      ),
  });

  const summary = meta?.ai_summary ?? result;
  if (summary) {
    return <SummaryBlock summary={summary} abstractRaw={meta?.abstract_raw} />;
  }

  if (isOwner && meta?.abstract_raw) {
    return (
      <div className="mt-6">
        <h2 className="text-base font-semibold tracking-tight">Summary</h2>
        <p className="text-muted-foreground mt-2 text-sm">
          The linked paper has an abstract but no summary yet.
        </p>
        <Button
          size="sm"
          variant="outline"
          className="mt-2"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Summarizing…" : "Summarize with AI"}
        </Button>
        {note && <p className="text-muted-foreground mt-2 text-xs">{note}</p>}
      </div>
    );
  }

  return null;
}
