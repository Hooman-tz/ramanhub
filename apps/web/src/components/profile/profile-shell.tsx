"use client";

import { useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  FileEdit,
  FlaskConical,
  LayoutGrid,
  Newspaper,
  SlidersHorizontal,
  Users,
} from "lucide-react";

import type { PublicProfile } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";

import type { NavSection } from "~/components/profile/profile-nav";
import { OverviewSection } from "~/components/profile/overview-section";
import { ProfileNav } from "~/components/profile/profile-nav";
import {
  ConnectionsTab,
  DraftsTab,
  LibraryTab,
  PostsTab,
} from "~/components/profile/profile-tabs";
import { Workbench } from "~/components/profile/workbench";

const OWNER_SECTIONS: NavSection[] = [
  { id: "overview", label: "Overview", icon: LayoutGrid },
  { id: "posts", label: "Posts", icon: Newspaper },
  { id: "drafts", label: "Drafts", icon: FileEdit },
  { id: "library", label: "Library", icon: FlaskConical },
  { id: "workbench", label: "Workbench", icon: SlidersHorizontal },
  { id: "connections", label: "Connections", icon: Users },
];

const VISITOR_SECTIONS: NavSection[] = [
  { id: "overview", label: "Overview", icon: LayoutGrid },
  { id: "posts", label: "Posts", icon: Newspaper },
  { id: "connections", label: "Connections", icon: Users },
];

export function ProfileShell({
  profile,
  isOwner,
}: {
  profile: PublicProfile;
  isOwner: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const handle = profile.profile_handle ?? "";

  const sections = isOwner ? OWNER_SECTIONS : VISITOR_SECTIONS;
  const requested = searchParams.get("tab") ?? "overview";
  const active = sections.some((s) => s.id === requested)
    ? requested
    : "overview";

  const go = useCallback(
    (id: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", id);
      if (id !== "workbench") params.delete("s");
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  const isWorkbench = active === "workbench";

  return (
    <div
      className={cn(
        "mt-6 w-full px-4",
        isWorkbench ? "mx-auto max-w-[1500px]" : "mx-auto max-w-5xl",
      )}
    >
      <div className="flex flex-col gap-4 md:flex-row md:gap-6">
        <ProfileNav sections={sections} active={active} onSelect={go} />

        <div className="min-w-0 flex-1">
          {active === "overview" && (
            <OverviewSection
              handle={handle}
              isOwner={isOwner}
              onSeeAllPosts={() => go("posts")}
            />
          )}
          {active === "posts" && <PostsTab handle={handle} />}
          {active === "connections" && <ConnectionsTab handle={handle} />}
          {isOwner && active === "drafts" && <DraftsTab />}
          {isOwner && active === "library" && <LibraryTab />}
          {isOwner && active === "workbench" && <Workbench />}
        </div>
      </div>
    </div>
  );
}
