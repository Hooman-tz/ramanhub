"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { isApiError, updateFinding } from "@ramanhub/api-client";
import { Button } from "@ramanhub/ui/button";

import { Markdown } from "~/components/markdown";

/**
 * Inline editor for an owned **draft** finding's title / abstract / tags.
 * Read view mirrors the static page block with an "Edit" toggle; the form
 * PATCHes `/v1/findings/{id}` and calls `router.refresh()` on success so the
 * server component re-renders with the saved values.
 */
export function FindingEditor({
  id,
  initialTitle,
  initialAbstract,
  initialTags,
}: {
  id: string;
  initialTitle: string;
  initialAbstract: string | null;
  initialTags: string[] | null;
}) {
  const router = useRouter();
  const qc = useQueryClient();

  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(initialTitle);
  const [abstract, setAbstract] = useState(initialAbstract ?? "");
  const [tags, setTags] = useState((initialTags ?? []).join(", "));
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parseTags = () =>
    tags
      .split(/[,\s]+/)
      .map((t) => t.trim())
      .filter(Boolean);

  const reset = () => {
    setTitle(initialTitle);
    setAbstract(initialAbstract ?? "");
    setTags((initialTags ?? []).join(", "));
    setError(null);
  };

  const save = useMutation({
    // Send "" / [] rather than undefined so cleared fields actually clear —
    // the backend guards with `is not None`, so empty string / empty list work
    // but `null` would be ignored.
    mutationFn: () =>
      updateFinding(id, {
        title: title.trim(),
        abstract_md: abstract.trim(),
        tags: parseTags(),
      }),
    onSuccess: () => {
      setError(null);
      setSaved(true);
      void qc.invalidateQueries({ queryKey: ["finding", id] });
      router.refresh();
    },
    onError: (e) => {
      setSaved(false);
      setError(isApiError(e) ? e.message : "Could not save.");
    },
  });

  if (!editing) {
    return (
      <div className="mt-2">
        <div className="flex items-start justify-between gap-3">
          <h1 className="text-2xl font-bold tracking-tight">{initialTitle}</h1>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-1 shrink-0"
            onClick={() => {
              reset();
              setSaved(false);
              setEditing(true);
            }}
          >
            Edit
          </Button>
        </div>

        {initialAbstract && (
          <div className="mt-3">
            <Markdown>{initialAbstract}</Markdown>
          </div>
        )}

        {initialTags && initialTags.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
            {initialTags.map((t) => (
              <span
                key={t}
                className="bg-muted text-foreground/80 rounded px-1.5 py-0.5"
              >
                #{t}
              </span>
            ))}
          </div>
        )}

        {saved && (
          <p className="mt-3 text-xs text-emerald-600 dark:text-emerald-400">
            Saved.
          </p>
        )}
      </div>
    );
  }

  return (
    <form
      className="border-border bg-card mt-2 space-y-3 rounded-xl border p-4 shadow-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (title.trim()) save.mutate();
      }}
    >
      <div className="space-y-1.5">
        <label htmlFor="finding-title" className="text-sm font-medium">
          Title
        </label>
        <input
          id="finding-title"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
            setSaved(false);
          }}
          placeholder="Title"
          className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm focus-visible:ring-[3px] focus-visible:outline-none"
          required
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="finding-abstract" className="text-sm font-medium">
          Abstract
        </label>
        <textarea
          id="finding-abstract"
          value={abstract}
          onChange={(e) => {
            setAbstract(e.target.value);
            setSaved(false);
          }}
          placeholder="Abstract (markdown)"
          rows={6}
          className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm leading-relaxed focus-visible:ring-[3px] focus-visible:outline-none"
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="finding-tags" className="text-sm font-medium">
          Tags
        </label>
        <input
          id="finding-tags"
          value={tags}
          onChange={(e) => {
            setTags(e.target.value);
            setSaved(false);
          }}
          placeholder="tags, comma or space separated"
          className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm focus-visible:ring-[3px] focus-visible:outline-none"
        />
      </div>

      {error && (
        <p className="text-destructive text-xs" role="alert">
          {error}
        </p>
      )}
      {saved && !save.isPending && (
        <p className="text-xs text-emerald-600 dark:text-emerald-400">Saved.</p>
      )}

      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={save.isPending}
          onClick={() => {
            reset();
            setEditing(false);
          }}
        >
          Done
        </Button>
        <Button
          type="submit"
          size="sm"
          disabled={save.isPending || !title.trim()}
        >
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </div>
    </form>
  );
}
