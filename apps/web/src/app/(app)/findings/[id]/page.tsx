import Link from "next/link";
import { notFound } from "next/navigation";

import type {
  FindingComment,
  FindingShares,
  FindingVotes,
} from "@ramanhub/api-client";
import {
  getFinding,
  getFindingShares,
  getFindingVotes,
  getSession,
  isApiError,
  listFindingComments,
} from "@ramanhub/api-client";
import { Card } from "@ramanhub/ui/card";

import { AbstractSummary } from "~/components/abstract-summary";
import { BackLink } from "~/components/back-link";
import { DeleteRecordButton } from "~/components/delete-record-button";
import { FindingActions } from "~/components/finding-actions";
import { FindingComments } from "~/components/finding-comments";
import { FindingEditor } from "~/components/finding-editor";
import { ForkDataButton } from "~/components/fork-data-button";
import { JournalCard } from "~/components/journal-card";
import { Markdown } from "~/components/markdown";
import { PostDataCard } from "~/components/post-data-card";
import { PostGallery } from "~/components/post-gallery";
import { PinButton } from "~/components/profile/pin-button";
import { ProvenanceTrail } from "~/components/provenance-trail";
import { serverApiOpts } from "~/lib/server-api";

export const dynamic = "force-dynamic";

export default async function FindingPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const opts = await serverApiOpts();
  let finding;
  try {
    finding = await getFinding(id, opts);
  } catch (e) {
    if (isApiError(e) && e.status === 404) notFound();
    throw e;
  }

  // Seed the client islands so they render without a flash. Never fatal.
  let initialVotes: FindingVotes | undefined;
  let initialShares: FindingShares | undefined;
  let initialComments: FindingComment[] | undefined;
  let isOwner = false;
  try {
    const [votes, shares, comments, session] = await Promise.all([
      getFindingVotes(id, opts),
      getFindingShares(id, opts),
      listFindingComments(id, opts),
      getSession(opts),
    ]);
    initialVotes = votes;
    initialShares = shares;
    initialComments = comments;
    isOwner = !!session && session.id === finding.owner_id;
  } catch {
    /* islands will fetch client-side */
  }

  const members = finding.spectra.map((s) => ({
    spectrum_id: s.spectrum_id,
    label: s.label ?? s.title ?? s.accession,
  }));

  // Lineage is per-spectrum; the first member is the representative one. A
  // post whose data was forked has the same origin for every member in
  // practice, because forking copies a whole dataset at once.
  const lineageAnchor = finding.spectra[0]?.spectrum_id;

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8">
      <BackLink />

      {lineageAnchor && <ProvenanceTrail spectrumId={lineageAnchor} />}

      <div className="text-foreground/80 mt-4 flex flex-wrap items-center gap-2 text-xs">
        {finding.owner_handle ? (
          <Link
            href={`/u/${finding.owner_handle}`}
            className="hover:text-foreground font-medium"
          >
            {finding.owner_display_name ?? finding.owner_handle}
          </Link>
        ) : (
          <span className="font-medium">
            {finding.owner_display_name ?? "Someone"}
          </span>
        )}
        {finding.accession && (
          <span className="font-mono">· {finding.accession}</span>
        )}
        <span
          className={
            finding.state === "published"
              ? "text-primary"
              : "text-muted-foreground"
          }
        >
          · {finding.state}
        </span>
      </div>

      {isOwner && finding.state === "draft" ? (
        <FindingEditor
          id={finding.id}
          initialTitle={finding.title}
          initialAbstract={finding.abstract_md}
          initialTags={finding.tags}
        />
      ) : (
        <>
          <h1 className="mt-2 text-2xl font-bold tracking-tight">
            {finding.title}
          </h1>

          {finding.abstract_md && (
            <div className="mt-3">
              <Markdown>{finding.abstract_md}</Markdown>
            </div>
          )}

          {finding.tags && finding.tags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
              {finding.tags.map((t) => (
                <span
                  key={t}
                  className="bg-muted text-foreground/80 rounded px-1.5 py-0.5"
                >
                  #{t}
                </span>
              ))}
            </div>
          )}
        </>
      )}

      {finding.doi && !finding.publication_metadata && (
        <div className="mt-4 text-xs">
          <a
            href={`https://doi.org/${finding.doi}`}
            className="text-primary hover:underline"
          >
            {finding.doi}
          </a>
        </div>
      )}

      {/* The figures are the payload, so they sit directly under the abstract
          — before the vote/share bar rather than after it, which used to split
          the write-up from the thing it is about. */}
      {(members.length > 0 || finding.images.length > 0 || isOwner) && (
        <section className="mt-6" aria-label="Figures and spectra">
          <PostGallery
            variant="full"
            findingId={finding.id}
            members={members}
            images={finding.images}
            isOwner={isOwner}
            title={finding.title}
          />
        </section>
      )}

      {/* One action bar instead of three stacked rows: the primary action
          ("take this data") first, social signals next, owner controls pushed
          to the trailing edge where they don't compete with either. */}
      <div className="border-border mt-5 flex flex-wrap items-center gap-2 border-t pt-4">
        {members.length > 0 && (
          <ForkDataButton source="finding" id={finding.id} size="sm" />
        )}
        <FindingActions
          id={finding.id}
          initialVotes={
            initialVotes ?? {
              count: finding.vote_count,
              voted_by_me: false,
            }
          }
          initialShares={initialShares}
          className="mt-0"
        />
        {isOwner && (
          <div className="ml-auto flex items-center gap-1">
            {finding.state === "published" && (
              <PinButton kind="finding" id={finding.id} />
            )}
            {finding.state !== "published" && (
              <DeleteRecordButton
                kind="finding"
                id={finding.id}
                redirectTo="/office"
                variant="icon"
              />
            )}
          </div>
        )}
      </div>

      <PostDataCard finding={finding} />

      <JournalCard meta={finding.publication_metadata} />

      <AbstractSummary
        meta={finding.publication_metadata}
        findingId={finding.id}
        isOwner={isOwner}
      />

      {finding.entries.length > 0 && (
        <section className="mt-8" aria-labelledby="thread-heading">
          <h2
            id="thread-heading"
            className="text-muted-foreground mb-2 text-xs font-semibold tracking-wider uppercase"
          >
            Thread
          </h2>
          <Card className="gap-0 divide-y p-0">
            {finding.entries.map((entry) => (
              <div key={entry.id} className="p-3.5 text-sm">
                <div className="text-foreground/60 mb-1 text-xs tracking-wide uppercase">
                  {entry.kind}
                </div>
                {entry.body_md && <Markdown>{entry.body_md}</Markdown>}
              </div>
            ))}
          </Card>
        </section>
      )}

      <FindingComments id={finding.id} initial={initialComments} />
    </main>
  );
}
