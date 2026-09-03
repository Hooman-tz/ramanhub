"use client";

import { useRef, useState } from "react";
import { Bold, Code, Heading2, Italic, Link2, List, Quote } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@ramanhub/ui";

/**
 * A markdown textarea with a formatting toolbar and a preview tab.
 *
 * Deliberately not a rich-text/WYSIWYG editor. The body is stored as markdown
 * (`abstract_md`) and rendered as markdown everywhere else on the site, so an
 * editor that hid the syntax would be lying about what gets saved — and would
 * mangle the one thing researchers paste most, which is markdown from their
 * notes. The toolbar just writes the syntax for you.
 */

interface ToolbarAction {
  icon: typeof Bold;
  label: string;
  /** Wraps the selection, or prefixes the line when `block` is set. */
  before: string;
  after?: string;
  block?: boolean;
  placeholder: string;
}

const ACTIONS: ToolbarAction[] = [
  {
    icon: Bold,
    label: "Bold",
    before: "**",
    after: "**",
    placeholder: "bold text",
  },
  {
    icon: Italic,
    label: "Italic",
    before: "_",
    after: "_",
    placeholder: "italic",
  },
  {
    icon: Heading2,
    label: "Heading",
    before: "## ",
    block: true,
    placeholder: "Heading",
  },
  {
    icon: List,
    label: "Bulleted list",
    before: "- ",
    block: true,
    placeholder: "item",
  },
  {
    icon: Quote,
    label: "Quote",
    before: "> ",
    block: true,
    placeholder: "quoted text",
  },
  { icon: Code, label: "Code", before: "`", after: "`", placeholder: "code" },
  {
    icon: Link2,
    label: "Link",
    before: "[",
    after: "](https://)",
    placeholder: "link text",
  },
];

export function MarkdownEditor({
  id,
  value,
  onChange,
  placeholder,
  rows = 6,
  label,
}: {
  id: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  rows?: number;
  label: string;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const [tab, setTab] = useState<"write" | "preview">("write");

  function apply(action: ToolbarAction) {
    const el = ref.current;
    if (!el) return;

    const start = el.selectionStart;
    const end = el.selectionEnd;
    const selected = value.slice(start, end);

    let next: string;
    let caretStart: number;
    let caretEnd: number;

    if (action.block) {
      // Block marks belong at the start of the line, not at the cursor.
      const lineStart = value.lastIndexOf("\n", start - 1) + 1;
      const text = selected || action.placeholder;
      next =
        value.slice(0, lineStart) +
        action.before +
        value.slice(lineStart, start) +
        text +
        value.slice(end);
      caretStart = lineStart + action.before.length + (start - lineStart);
      caretEnd = caretStart + text.length;
    } else {
      const text = selected || action.placeholder;
      const after = action.after ?? "";
      next =
        value.slice(0, start) + action.before + text + after + value.slice(end);
      caretStart = start + action.before.length;
      caretEnd = caretStart + text.length;
    }

    onChange(next);
    // Restore the selection after React re-renders with the new value, so the
    // inserted placeholder is selected and can be typed straight over.
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caretStart, caretEnd);
    });
  }

  const tabClass = (active: boolean) =>
    cn(
      "cursor-pointer rounded-md px-2 py-1 text-xs font-medium transition-colors duration-150 outline-none",
      "focus-visible:ring-ring/50 focus-visible:ring-[3px] motion-reduce:transition-none",
      active
        ? "bg-background text-foreground shadow-sm"
        : "text-muted-foreground hover:text-foreground",
    );

  return (
    <div className="border-input focus-within:border-ring rounded-md border transition-colors motion-reduce:transition-none">
      <div className="border-input flex flex-wrap items-center gap-1 border-b px-1.5 py-1">
        <div className="bg-muted flex items-center gap-0.5 rounded-lg p-0.5">
          <button
            type="button"
            onClick={() => setTab("write")}
            className={tabClass(tab === "write")}
          >
            Write
          </button>
          <button
            type="button"
            onClick={() => setTab("preview")}
            className={tabClass(tab === "preview")}
          >
            Preview
          </button>
        </div>

        {tab === "write" && (
          <div className="ml-1 flex flex-wrap items-center gap-0.5">
            {ACTIONS.map((action) => {
              const Icon = action.icon;
              return (
                <button
                  key={action.label}
                  type="button"
                  title={action.label}
                  aria-label={action.label}
                  // Keep the textarea's selection: focus would otherwise move
                  // to the button before the click handler reads it.
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => apply(action)}
                  className="text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-ring/50 flex size-7 cursor-pointer items-center justify-center rounded-md transition-colors duration-150 focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
                >
                  <Icon className="size-3.5" aria-hidden />
                </button>
              );
            })}
          </div>
        )}
      </div>

      {tab === "write" ? (
        <>
          <label htmlFor={id} className="sr-only">
            {label}
          </label>
          <textarea
            id={id}
            ref={ref}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            rows={rows}
            className="bg-background w-full resize-y rounded-b-md px-3 py-2 text-sm leading-relaxed focus:outline-none"
          />
        </>
      ) : (
        <div className="min-h-24 px-3 py-2">
          {value.trim() ? (
            <div className="prose prose-sm dark:prose-invert max-w-none text-sm leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">Nothing to preview.</p>
          )}
        </div>
      )}
    </div>
  );
}
