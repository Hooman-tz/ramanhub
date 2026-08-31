import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@ramanhub/ui";

/**
 * Minimal prose renderer. There's no `@tailwindcss/typography` in the
 * workspace, so headings / lists / code / links are styled by hand with
 * child selectors on a wrapper.
 */
export function Markdown({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "text-foreground/90 text-sm leading-relaxed",
        "[&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:text-lg [&_h1]:font-semibold",
        "[&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold",
        "[&_h3]:mt-3 [&_h3]:mb-1.5 [&_h3]:text-sm [&_h3]:font-semibold",
        "[&_p]:my-2",
        "[&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5",
        "[&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5",
        "[&_li]:my-0.5",
        "[&_a]:text-primary [&_a]:underline [&_a]:underline-offset-2",
        "[&_code]:bg-muted [&_code]:rounded [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[0.85em]",
        "[&_pre]:bg-muted [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:p-3",
        "[&_pre_code]:bg-transparent [&_pre_code]:p-0",
        "[&_blockquote]:border-border [&_blockquote]:text-muted-foreground [&_blockquote]:my-2 [&_blockquote]:border-l-2 [&_blockquote]:pl-3",
        "[&_table]:my-2 [&_table]:w-full [&_table]:text-left",
        "[&_th]:border-border [&_th]:border-b [&_th]:py-1 [&_th]:pr-3 [&_th]:font-semibold",
        "[&_td]:border-border/50 [&_td]:border-b [&_td]:py-1 [&_td]:pr-3",
        "[&_hr]:border-border [&_hr]:my-4",
        className,
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}
