import Link from "next/link";
import { ArrowLeft } from "lucide-react";

/**
 * Small "back to somewhere" link — icon + text, with a visible focus ring and
 * a hover colour shift. Defaults to the feed.
 */
export function BackLink({
  href = "/",
  children = "Feed",
}: {
  href?: string;
  children?: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 -mx-1 inline-flex items-center gap-1.5 rounded-md px-1 py-1 text-sm transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
    >
      <ArrowLeft className="size-4" aria-hidden />
      {children}
    </Link>
  );
}
