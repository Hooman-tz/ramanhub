import { ThemeToggle } from "@ramanhub/ui/theme";

import { Providers } from "~/app/providers";
import { AppShell } from "~/components/app-shell";

/**
 * Everything that is "the application": the TanStack query client, the
 * onboarding guard, the nav / zone wash / mobile nav / ⌘K chrome, and the
 * floating theme toggle whose mobile offset assumes the fixed bottom nav.
 *
 * Marketing routes sit deliberately outside this group. That is what keeps the
 * landing page free of a session round-trip — `RequireOnboarding` fires an
 * unconditional `["session"]` query the moment it mounts, so it must not wrap
 * a page we want to stay static.
 */
export default function AppLayout(props: { children: React.ReactNode }) {
  return (
    <Providers>
      <AppShell>{props.children}</AppShell>
      <div className="fixed bottom-[calc(4.5rem+env(safe-area-inset-bottom))] left-4 z-30 md:right-4 md:bottom-4 md:left-auto">
        <ThemeToggle />
      </div>
    </Providers>
  );
}
