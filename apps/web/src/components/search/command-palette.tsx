"use client";

import type { ComponentType } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Atom, FileText, User, Waves } from "lucide-react";

import type { SuggestKind } from "@ramanhub/api-client";
import { suggest } from "@ramanhub/api-client";
import { Combobox } from "@ramanhub/ui/combobox";
import { Dialog, DialogContent, DialogTitle } from "@ramanhub/ui/dialog";

import { useDebounced } from "~/hooks/use-debounced";

import { hrefForSuggestion } from "./href-for-suggestion";

/**
 * Search everything from anywhere: ⌘K (or `/`), one box, results grouped by
 * what they are.
 *
 * Before this the only search box in the app rendered on the feed and nowhere
 * else, so from any other page there was no way to look anything up.
 *
 * No new dependency. Radix's Dialog already gives the focus trap, Escape,
 * scroll lock and portal; the shared Combobox gives the listbox semantics and
 * arrow-key handling, including across group headings. Together that is what
 * cmdk would have been imported for.
 */

const ICONS: Record<SuggestKind, ComponentType<{ className?: string }>> = {
  compound: Atom,
  spectrum: Waves,
  finding: FileText,
  person: User,
};

const OPEN_EVENT = "ramanhub:open-search";

/**
 * Open the palette from anywhere. An event rather than context: the only
 * shared state is one boolean, and a provider wrapped around the whole app to
 * carry it would be more machinery than the problem deserves.
 */
export function openCommandPalette() {
  window.dispatchEvent(new CustomEvent(OPEN_EVENT));
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || target.isContentEditable;
}

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
        return;
      }
      // `/` is only a shortcut when you are not already typing something —
      // otherwise it would eat the character in the composer.
      if (e.key === "/" && !isTypingTarget(e.target)) {
        e.preventDefault();
        setOpen(true);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_EVENT, onOpen);
    };
  }, []);

  const debounced = useDebounced(value.trim(), 200);

  const results = useQuery({
    queryKey: ["suggest", debounced],
    queryFn: ({ signal }) => suggest({ q: debounced, limit: 5 }, { signal }),
    enabled: debounced.length >= 2,
    // Without this the list empties between keystrokes and strobes.
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  // One flat array, so the Combobox's highlight can walk across groups; the
  // `group` label is what turns it back into sections when rendering.
  const items = useMemo(
    () =>
      (results.data?.groups ?? []).flatMap((g) =>
        g.items.map((item) => ({ ...item, group: g.label })),
      ),
    [results.data],
  );

  const go = useCallback(
    (href: string) => {
      setOpen(false);
      setValue("");
      router.push(href);
    },
    [router],
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        showCloseButton={false}
        className="top-[15%] max-w-xl translate-y-0 gap-0 p-0"
        aria-describedby={undefined}
      >
        {/* Radix requires a title; the box explains itself visually. */}
        <DialogTitle className="sr-only">Search RamanHub</DialogTitle>

        <Combobox
          items={items}
          value={value}
          onValueChange={setValue}
          onSelect={(item) => go(hrefForSuggestion(item))}
          // Enter with nothing highlighted falls through to the feed, so the
          // palette always has somewhere to send you.
          onSubmitRaw={(raw) =>
            raw.trim() && go(`/?q=${encodeURIComponent(raw.trim())}`)
          }
          listboxId="command-palette-results"
          forceOpen
          className="w-full"
          listClassName="relative mt-0 max-h-[60vh] overflow-y-auto rounded-none border-0 border-t shadow-none"
          inputProps={{
            autoFocus: true,
            placeholder: "Search compounds, spectra, findings, people…",
            "aria-label": "Search RamanHub",
            className:
              "placeholder:text-muted-foreground w-full bg-transparent px-4 py-3.5 text-sm focus:outline-none",
          }}
          emptyState={
            <li role="presentation" className="text-muted-foreground px-4 py-6 text-sm">
              {debounced.length < 2
                ? "Type at least two characters."
                : results.isFetching
                  ? "Searching…"
                  : `Nothing matches “${debounced}”. Press Enter to search the feed.`}
            </li>
          }
          renderItem={(item) => {
            const Icon = ICONS[item.kind];
            return (
              <span className="flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm">
                <Icon className="text-muted-foreground size-4 shrink-0" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{item.title}</span>
                  {item.subtitle && (
                    <span className="text-muted-foreground block truncate text-xs">
                      {item.kind === "person" ? `@${item.handle} · ` : ""}
                      {item.subtitle}
                    </span>
                  )}
                </span>
                {item.badge && (
                  <span className="text-muted-foreground bg-muted shrink-0 rounded px-1.5 py-0.5 text-[10px]">
                    {item.badge}
                  </span>
                )}
              </span>
            );
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
