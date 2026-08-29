"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { getSession } from "@ramanhub/api-client";

/** Paths a not-yet-onboarded full user is still allowed to sit on. */
const ALLOWED = ["/onboarding", "/login"];

/**
 * Client guard: if a signed-in (non-guest) user has never completed onboarding,
 * push them to `/onboarding`. Never touches guests or signed-out visitors, and
 * only runs its check in an effect so it cannot cause hydration mismatches.
 */
export function RequireOnboarding({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });

  useEffect(() => {
    const user = session.data;
    if (!user || user.is_guest) return;
    if (user.onboarded_at != null) return;
    if (ALLOWED.some((p) => pathname === p || pathname.startsWith(`${p}/`)))
      return;
    router.replace("/onboarding");
  }, [session.data, pathname, router]);

  return <>{children}</>;
}
