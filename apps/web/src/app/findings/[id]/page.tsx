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

import { AbstractSummary } from "~/components/abstract-summary";
import { BackLink } from "~/components/back-link";
import { FindingActions } from "~/components/finding-actions";
import { FindingComments } from "~/components/finding-comments";
import { FindingImageUploader } from "~/components/finding-image-uploader";
import { JournalCard } from "~/components/journal-card";
import { Markdown } from "~/components/markdown";
import { PostGallery } from "~/components/post-gallery";
import { PinButton } from "~/components/profile/pin-button";
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

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8">
      <BackLink />

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

      <FindingActions
        id={finding.id}
        initialVotes={
          initialVotes ?? {
            count: finding.vote_count,
            voted_by_me: false,
          }
        }
        initialShares={initialShares}
      />

      {isOwner && finding.state === "published" && (
        <div className="mt-3">
          <PinButton kind="finding" id={finding.id} />
        </div>
      )}

      {(members.length > 0 || finding.images.length > 0) && (
        <section className="mt-6">
          <PostGallery
            variant="full"
            findingId={finding.id}
            members={members}
            images={finding.images}
          />
        </section>
      )}

      <JournalCard meta={finding.publication_metadata} />

      <AbstractSummary
        meta={finding.publication_metadata}
        findingId={finding.id}
        isOwner={isOwner}
      />

      {isOwner && (
        <FindingImageUploader findingId={finding.id} images={finding.images} />
      )}

      {finding.entries.length > 0 && (
        <section className="mt-8 space-y-4">
          <h2 className="text-base font-semibold tracking-tight">Thread</h2>
          {finding.entries.map((entry) => (
            <div
              key={entry.id}
              className="border-border rounded-lg border p-3.5 text-sm"
            >
              <div className="text-foreground/60 mb-1 text-xs tracking-wide uppercase">
                {entry.kind}
              </div>
              {entry.body_md && <Markdown>{entry.body_md}</Markdown>}
            </div>
          ))}
        </section>
      )}

      <FindingComments id={finding.id} initial={initialComments} />
    </main>
  );
}
