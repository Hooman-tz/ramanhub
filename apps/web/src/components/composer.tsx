"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  Github,
  ImageIcon,
  LineChart,
  Link2,
  Plus,
  Users,
  X,
} from "lucide-react";

import type { SessionUser } from "@ramanhub/api-client";
import {
  attachFindingSpectrum,
  createFinding,
  isApiError,
  linkFindingDoi,
  publishFinding,
} from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Avatar, AvatarFallback, AvatarImage } from "@ramanhub/ui/avatar";
import { Button } from "@ramanhub/ui/button";
import { Label } from "@ramanhub/ui/label";

import { MarkdownEditor } from "./markdown-editor";
import { SpectrumPickerDialog } from "./spectrum-picker";

/**
 * `dialog`   — bare form, no card chrome; used inside the compose dialog
 *              (FAB / nav "+"). Renders the form directly.
 * `expanded` — the feed's inline composer. Collapsed to a single line until
 *              the "+" is pressed: the feed is for reading, and a multi-field
 *              form sitting permanently above it pushed the actual posts down
 *              for everyone who wasn't writing one.
 *
 * ## Two exits, not one
 *
 * A post with nothing attached is published immediately — that is the
 * low-friction "note to the feed" path the feed is built around.
 *
 * A post *with spectra* is deliberately left as a draft and opens the finding
 * editor instead. Publishing a finding requires its spectra to be published
 * too (a public write-up pointing at private data renders as a wall of 404s),
 * so auto-publishing here would fail for exactly the people doing the most
 * careful work. Handing them the draft is the honest move.
 */
export type ComposerVariant = "dialog" | "expanded";

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

const fieldClass =
  "border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm focus-visible:ring-[3px] focus-visible:outline-none";

/** Handle chips — co-authors are addressed by handle and validated server-side. */
function CoAuthorField({
  handles,
  onChange,
}: {
  handles: string[];
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  const commit = () => {
    const handle = draft.trim().replace(/^@/, "");
    if (!handle) return;
    if (!handles.some((h) => h.toLowerCase() === handle.toLowerCase())) {
      onChange([...handles, handle]);
    }
    setDraft("");
  };

  return (
    <div className="space-y-1">
      <Label htmlFor="composer-coauthors" className="text-xs">
        <Users className="mr-1 inline size-3.5" aria-hidden />
        Co-authors
      </Label>
      <div className="border-input bg-background focus-within:border-ring flex flex-wrap items-center gap-1.5 rounded-md border px-2 py-1.5">
        {handles.map((handle) => (
          <span
            key={handle}
            className="bg-muted inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
          >
            @{handle}
            <button
              type="button"
              aria-label={`Remove @${handle}`}
              onClick={() => onChange(handles.filter((h) => h !== handle))}
              className="text-muted-foreground hover:text-foreground cursor-pointer"
            >
              <X className="size-3" aria-hidden />
            </button>
          </span>
        ))}
        <input
          id="composer-coauthors"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            // Enter must not submit the form — it commits a chip.
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              commit();
            } else if (e.key === "Backspace" && !draft && handles.length) {
              onChange(handles.slice(0, -1));
            }
          }}
          onBlur={commit}
          placeholder={handles.length ? "" : "@handle"}
          className="min-w-24 flex-1 bg-transparent py-0.5 text-sm focus:outline-none"
        />
      </div>
      <p className="text-foreground/60 text-xs">
        Handles of people with an account here — they&apos;ll link to their
        profiles.
      </p>
    </div>
  );
}

export function Composer({
  session,
  variant = "dialog",
  onPosted,
}: {
  session: SessionUser | null;
  variant?: ComposerVariant;
  /** Called after a successful post (e.g. to close the dialog). */
  onPosted?: () => void;
}) {
  const qc = useQueryClient();
  const router = useRouter();

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [nextSteps, setNextSteps] = useState("");
  const [tags, setTags] = useState("");
  const [doi, setDoi] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [coAuthors, setCoAuthors] = useState<string[]>([]);
  const [spectrumIds, setSpectrumIds] = useState<string[]>([]);
  const [showMore, setShowMore] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Only meaningful for `expanded`; the dialog variant is already open. */
  const [open, setOpen] = useState(false);

  const parseTags = () =>
    tags
      .split(/[,\s]+/)
      .map((t) => t.trim())
      .filter(Boolean);

  const reset = () => {
    setTitle("");
    setBody("");
    setNextSteps("");
    setTags("");
    setDoi("");
    setRepoUrl("");
    setCoAuthors([]);
    setSpectrumIds([]);
    setShowMore(false);
    setError(null);
  };

  /**
   * Create the draft, attach everything, then either publish it or hand back
   * the draft. Sequential rather than parallel because each step needs the
   * finding id, and because a failure part-way should leave a recoverable
   * draft rather than a half-published record.
   */
  const submit = useMutation({
    mutationFn: async (mode: "post" | "draft") => {
      const finding = await createFinding({
        title: title.trim(),
        ...(body.trim() ? { abstract_md: body.trim() } : {}),
        ...(nextSteps.trim() ? { next_steps_md: nextSteps.trim() } : {}),
        tags: parseTags(),
        ...(repoUrl.trim() ? { repo_url: repoUrl.trim() } : {}),
        ...(coAuthors.length ? { co_author_handles: coAuthors } : {}),
      });

      for (const spectrumId of spectrumIds) {
        await attachFindingSpectrum(finding.id, spectrumId);
      }
      // Linking resolves the DOI against Crossref, so it goes after creation
      // and is allowed to be the slow step.
      if (doi.trim()) await linkFindingDoi(finding.id, doi.trim());

      if (mode === "draft") return { finding, published: false };
      return {
        finding: await publishFinding(finding.id, "CC-BY-4.0"),
        published: true,
      };
    },
    onSuccess: ({ finding, published }) => {
      void qc.invalidateQueries({ queryKey: ["feed"] });
      void qc.invalidateQueries({ queryKey: ["my-findings"] });
      reset();
      setOpen(false);
      if (published) onPosted?.();
      else router.push(`/findings/${finding.id}`);
    },
    onError: (e) =>
      setError(isApiError(e) ? e.message : "Could not post — try again."),
  });

  if (!session || session.is_guest) {
    return (
      <div className="border-border bg-card rounded-xl border p-4 text-sm shadow-sm">
        <p className="text-foreground/80">
          Sign in to post a note to the feed.
        </p>
        <Button asChild size="sm" className="mt-2">
          <a href="/login">Sign in</a>
        </Button>
      </div>
    );
  }

  const hasTitle = !!title.trim();
  const busy = submit.isPending;
  const expanded = variant === "expanded";
  // Spectra make this a finding, not a note — publishing needs them published.
  const hasAttachments = spectrumIds.length > 0;

  if (expanded && !open) {
    return (
      <div className="border-border bg-card flex items-center gap-3 rounded-xl border p-3 shadow-sm">
        <Avatar>
          {session.avatar_url ? (
            <AvatarImage
              src={session.avatar_url}
              alt={session.display_name ?? "You"}
            />
          ) : null}
          <AvatarFallback>{initials(session.display_name)}</AvatarFallback>
        </Avatar>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 min-w-0 flex-1 cursor-pointer rounded-md px-1 py-1.5 text-left text-sm transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
        >
          Share a note or a finding…
        </button>
        <Button
          type="button"
          size="icon"
          aria-label="Write a post"
          onClick={() => setOpen(true)}
        >
          <Plus className="size-4" aria-hidden />
        </Button>
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (hasTitle && !busy) submit.mutate(hasAttachments ? "draft" : "post");
      }}
      className={
        expanded
          ? "border-border bg-card space-y-3 rounded-xl border p-4 shadow-sm"
          : "space-y-3"
      }
    >
      {expanded && (
        <div className="flex items-center gap-3">
          <Avatar>
            {session.avatar_url ? (
              <AvatarImage
                src={session.avatar_url}
                alt={session.display_name ?? "You"}
              />
            ) : null}
            <AvatarFallback>{initials(session.display_name)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <p className="text-sm font-semibold tracking-tight">
              Share with the community
            </p>
            <p className="text-foreground/60 text-xs">
              Post a note, or start a finding with data.
            </p>
          </div>
        </div>
      )}

      <label htmlFor="composer-title" className="sr-only">
        Title
      </label>
      <input
        id="composer-title"
        autoFocus={variant === "dialog"}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title"
        className={fieldClass}
        required
      />

      <MarkdownEditor
        id="composer-body"
        label="Body"
        value={body}
        onChange={setBody}
        placeholder="What did you find? Markdown is supported."
        rows={5}
      />

      <div className="space-y-1">
        <label htmlFor="composer-tags" className="sr-only">
          Tags
        </label>
        <input
          id="composer-tags"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="tags, comma separated (optional)"
          className={fieldClass}
        />
      </div>

      {/* Attached spectra */}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => setPickerOpen(true)}
        >
          <LineChart aria-hidden />
          {spectrumIds.length
            ? `${spectrumIds.length} ${spectrumIds.length === 1 ? "spectrum" : "spectra"} attached`
            : "Attach spectra"}
        </Button>
        {spectrumIds.length > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => setSpectrumIds([])}
          >
            Clear
          </Button>
        )}
      </div>

      <button
        type="button"
        onClick={() => setShowMore((v) => !v)}
        aria-expanded={showMore}
        className="text-muted-foreground hover:text-foreground flex cursor-pointer items-center gap-1 text-xs font-medium transition-colors motion-reduce:transition-none"
      >
        <ChevronDown
          className={cn(
            "size-3.5 transition-transform motion-reduce:transition-none",
            showMore && "rotate-180",
          )}
          aria-hidden
        />
        {showMore ? "Fewer details" : "Add paper, code, co-authors, next steps"}
      </button>

      {showMore && (
        <div className="space-y-3 border-l-2 pl-3">
          <div className="space-y-1">
            <Label htmlFor="composer-doi" className="text-xs">
              <Link2 className="mr-1 inline size-3.5" aria-hidden />
              DOI of the paper
            </Label>
            <input
              id="composer-doi"
              value={doi}
              onChange={(e) => setDoi(e.target.value)}
              placeholder="10.1234/example"
              className={fieldClass}
            />
            <p className="text-foreground/60 text-xs">
              We look it up and pull in the title, authors and journal.
            </p>
          </div>

          <div className="space-y-1">
            <Label htmlFor="composer-repo" className="text-xs">
              <Github className="mr-1 inline size-3.5" aria-hidden />
              Code repository
            </Label>
            <input
              id="composer-repo"
              type="url"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/you/project"
              className={fieldClass}
            />
          </div>

          <CoAuthorField handles={coAuthors} onChange={setCoAuthors} />

          <div className="space-y-1">
            <Label className="text-xs">Next steps</Label>
            <MarkdownEditor
              id="composer-next-steps"
              label="Next steps"
              value={nextSteps}
              onChange={setNextSteps}
              placeholder="Open questions, what you'd try next, help you're looking for…"
              rows={3}
            />
          </div>
        </div>
      )}

      {error && (
        <p className="text-destructive text-xs" role="alert">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {expanded && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => submit.mutate("draft")}
          >
            <ImageIcon aria-hidden />
            Add figures
          </Button>
        )}
        {expanded && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="ml-auto"
            disabled={busy}
            onClick={() => {
              setOpen(false);
              setError(null);
            }}
          >
            Cancel
          </Button>
        )}
        <Button
          type="submit"
          size="sm"
          className={expanded ? undefined : "ml-auto"}
          disabled={!hasTitle || busy}
        >
          {busy
            ? hasAttachments
              ? "Creating…"
              : "Posting…"
            : hasAttachments
              ? "Continue to draft"
              : "Post"}
        </Button>
      </div>

      {hasAttachments && (
        <p className="text-foreground/60 text-xs">
          Posts with data open as a draft — publishing needs the attached
          spectra published too.
        </p>
      )}

      <SpectrumPickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        alreadyAttached={spectrumIds}
        onConfirm={(ids) =>
          setSpectrumIds((prev) => [...new Set([...prev, ...ids])])
        }
      />
    </form>
  );
}
