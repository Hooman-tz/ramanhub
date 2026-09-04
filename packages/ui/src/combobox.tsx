"use client";

import type { InputHTMLAttributes, KeyboardEvent, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { cn } from ".";

/**
 * The keyboard and ARIA half of a typeahead, without any opinion about where
 * the items come from.
 *
 * Extracted from the co-author field, which had all of this right already:
 * arrow keys that wrap, Enter committing either the highlighted item or the
 * raw text, Escape closing without clearing, a short blur delay so a click on
 * a suggestion lands before the list unmounts, and `onMouseDown`
 * preventDefault so that click does not blur the input first. Getting any one
 * of those wrong produces a box that looks finished and is unusable by
 * keyboard, which is why this is one component rather than three copies.
 *
 * Two things are new here. Items may carry a `group`, and consecutive items
 * sharing one render under a heading — but the highlight index walks the flat
 * array, so arrow keys cross group boundaries without the caller thinking
 * about it, and a grouped palette needs no separate implementation from a
 * flat field. And the input carries `aria-activedescendant`, which the
 * original was missing: focus never leaves the input, so without it a screen
 * reader is never told which option is current.
 *
 * Presentational only, hence its home in this package: it fetches nothing and
 * knows nothing about the API. `packages/ui` has no icon dependency, so
 * anything visual comes in through `renderItem`.
 */
export interface ComboboxItem {
  id: string;
  /** Optional heading; consecutive items sharing one are grouped under it. */
  group?: string;
}

export interface ComboboxProps<T extends ComboboxItem> {
  items: T[];
  /** Controlled input text. */
  value: string;
  onValueChange: (next: string) => void;
  onSelect: (item: T) => void;
  /** Enter with nothing highlighted. Omit to make Enter a no-op. */
  onSubmitRaw?: (value: string) => void;
  renderItem: (item: T, active: boolean) => ReactNode;
  /** Stable id, so `aria-controls` and `aria-activedescendant` can point at it. */
  listboxId: string;
  inputProps?: Omit<
    InputHTMLAttributes<HTMLInputElement>,
    "value" | "onChange" | "onKeyDown" | "onFocus" | "onBlur"
  >;
  /** Rendered in place of the list when open with no items. */
  emptyState?: ReactNode;
  /**
   * Wraps the input. Receives the input element so a caller can place it
   * inside its own container — the co-author field puts chips beside it in a
   * shared bordered box, which a plain `children` slot could not express.
   */
  children?: (input: ReactNode) => ReactNode;
  className?: string;
  listClassName?: string;
  blurDelayMs?: number;
  /** Force the list open — the palette wants it open while loading. */
  forceOpen?: boolean;
  /**
   * Escape with the list already closed. Escape always closes the list first
   * (what a combobox is expected to do); callers that also want Escape to
   * mean "clear the box" get it on the second press.
   */
  onEscape?: () => void;
}

export function Combobox<T extends ComboboxItem>({
  items,
  value,
  onValueChange,
  onSelect,
  onSubmitRaw,
  renderItem,
  listboxId,
  inputProps,
  emptyState,
  children,
  className,
  listClassName,
  blurDelayMs = 120,
  forceOpen = false,
  onEscape,
}: ComboboxProps<T>) {
  const [highlight, setHighlight] = useState(0);
  const [focused, setFocused] = useState(false);
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // A shrinking result set must not leave the highlight past the end.
  useEffect(() => {
    setHighlight((h) => (h < items.length ? h : 0));
  }, [items.length]);

  useEffect(
    () => () => {
      if (blurTimer.current) clearTimeout(blurTimer.current);
    },
    [],
  );

  const open = focused && (items.length > 0 || (forceOpen && !!emptyState));
  const activeId = open && items[highlight] ? `${listboxId}-${items[highlight].id}` : undefined;

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (open && items.length > 0 && e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => (h + 1) % items.length);
      return;
    }
    if (open && items.length > 0 && e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => (h - 1 + items.length) % items.length);
      return;
    }
    if (e.key === "Enter") {
      const picked = open ? items[highlight] : undefined;
      if (picked) {
        e.preventDefault();
        onSelect(picked);
        return;
      }
      if (onSubmitRaw) {
        e.preventDefault();
        onSubmitRaw(value);
      }
      return;
    }
    if (e.key === "Escape") {
      if (open) setFocused(false);
      else onEscape?.();
      return;
    }
    inputProps?.onKeyDownCapture?.(e);
  };

  let lastGroup: string | undefined;

  const input = (
    <input
        {...inputProps}
        value={value}
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        aria-controls={listboxId}
        aria-activedescendant={activeId}
        autoComplete="off"
        onChange={(e) => {
          onValueChange(e.target.value);
          setHighlight(0);
        }}
        onFocus={() => {
          if (blurTimer.current) clearTimeout(blurTimer.current);
          setFocused(true);
        }}
        onBlur={() => {
          // Let a click on a suggestion land before the list unmounts.
          blurTimer.current = setTimeout(() => setFocused(false), blurDelayMs);
        }}
      onKeyDown={onKeyDown}
    />
  );

  return (
    <div className={cn("relative", className)}>
      {children ? children(input) : input}

      {open && (
        <ul
          id={listboxId}
          role="listbox"
          className={cn(
            "border-border bg-popover absolute z-50 mt-1 w-full overflow-hidden rounded-md border shadow-lg",
            listClassName,
          )}
        >
          {items.length === 0
            ? emptyState
            : items.map((item, i) => {
                const heading = item.group && item.group !== lastGroup ? item.group : null;
                lastGroup = item.group;
                return (
                  <li key={item.id} role="presentation">
                    {heading && (
                      <div
                        role="presentation"
                        className="text-muted-foreground px-2 pt-2 pb-1 text-[11px] font-medium tracking-wide uppercase"
                      >
                        {heading}
                      </div>
                    )}
                    <div
                      id={`${listboxId}-${item.id}`}
                      role="option"
                      aria-selected={i === highlight}
                      // Mouse-down would blur the input and close the list
                      // before the click ever registered.
                      onMouseDown={(e) => e.preventDefault()}
                      onMouseEnter={() => setHighlight(i)}
                      onClick={() => onSelect(item)}
                      className={cn(
                        "cursor-pointer transition-colors duration-150 motion-reduce:transition-none",
                        i === highlight ? "bg-accent" : "hover:bg-muted",
                      )}
                    >
                      {renderItem(item, i === highlight)}
                    </div>
                  </li>
                );
              })}
        </ul>
      )}
    </div>
  );
}
