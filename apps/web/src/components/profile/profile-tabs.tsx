"use client";

import type { ReactNode } from "react";
import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  createRoutine,
  deleteRoutine,
  getAlgorithmCatalog,
  getFeed,
  getMyLibrary,
  listFollowers,
  listFollowing,
  listMyFindings,
  listRoutines,
} from "@ramanhub/api-client";
import type {
  FollowUser,
  LibraryParams,
  LibrarySpectrum,
  PublicProfile,
} from "@ramanhub/api-client";

import { Avatar, AvatarFallback, AvatarImage } from "@ramanhub/ui/avatar";
import { Badge } from "@ramanhub/ui/badge";
import { Button } from "@ramanhub/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@ramanhub/ui/dialog";
import { Input } from "@ramanhub/ui/input";
import { Label } from "@ramanhub/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ramanhub/ui/tabs";

import { FeedCard } from "~/components/feed-card";
import { FollowButton } from "~/components/follow-button";

const OWNER_TABS = [
  "posts",
  "drafts",
  "library",
  "workspace",
  "connections",
] as const;
const VISITOR_TABS = ["posts", "connections"] as const;

export function ProfileTabs({
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

  const tabs: readonly string[] = isOwner ? OWNER_TABS : VISITOR_TABS;
  const requested = searchParams.get("tab") ?? "posts";
  const active = tabs.includes(requested) ? requested : "posts";

  function setTab(value: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", value);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  return (
    <Tabs value={active} onValueChange={setTab}>
      <TabsList className="flex-wrap">
        {tabs.map((t) => (
          <TabsTrigger key={t} value={t} className="capitalize">
            {t}
          </TabsTrigger>
        ))}
      </TabsList>

      <TabsContent value="posts" className="mt-4">
        <PostsTab handle={handle} />
      </TabsContent>
      <TabsContent value="connections" className="mt-4">
        <ConnectionsTab handle={handle} />
      </TabsContent>
      {isOwner && (
        <>
          <TabsContent value="drafts" className="mt-4">
            <DraftsTab />
          </TabsContent>
          <TabsContent value="library" className="mt-4">
            <LibraryTab />
          </TabsContent>
          <TabsContent value="workspace" className="mt-4">
            <WorkspaceTab />
          </TabsContent>
        </>
      )}
    </Tabs>
  );
}

/* -------------------------------------------------------------------------- */

function Loading() {
  return <p className="text-muted-foreground text-sm">Loading…</p>;
}

function EmptyState({ children }: { children: ReactNode }) {
  return (
    <p className="text-muted-foreground rounded-xl border border-dashed p-6 text-center text-sm">
      {children}
    </p>
  );
}

/* --- Posts --------------------------------------------------------------- */

function PostsTab({ handle }: { handle: string }) {
  const feed = useQuery({
    queryKey: ["feed", "author", handle],
    queryFn: () => getFeed({ author: handle, limit: 50 }),
  });

  if (feed.isLoading) return <Loading />;
  const items = feed.data ?? [];
  if (items.length === 0) return <EmptyState>Nothing published yet.</EmptyState>;

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {items.map((item) => (
        <FeedCard key={`${item.kind}-${item.id}`} item={item} />
      ))}
    </div>
  );
}

/* --- Drafts ------------------------------------------------------------- */

function DraftsTab() {
  const findings = useQuery({
    queryKey: ["my-findings"],
    queryFn: () => listMyFindings(),
  });

  if (findings.isLoading) return <Loading />;
  const drafts = (findings.data ?? []).filter((f) => f.state === "draft");
  if (drafts.length === 0)
    return <EmptyState>No drafts — everything you have is published.</EmptyState>;

  return (
    <ul className="space-y-2">
      {drafts.map((d) => (
        <li
          key={d.id}
          className="border-border flex items-center justify-between gap-3 rounded-lg border p-3"
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{d.title}</p>
            <p className="text-muted-foreground text-xs">
              Updated {new Date(d.updated_at).toLocaleDateString()}
            </p>
          </div>
          <Link href={`/findings/${d.id}`}>
            <Button size="sm" variant="outline">
              Continue editing
            </Button>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/* --- Library ---------------------------------------------------------- */

interface LibFilters {
  material_type: string;
  excitation: string;
  min_snr: string;
}

const EMPTY_FILTERS: LibFilters = {
  material_type: "",
  excitation: "",
  min_snr: "",
};
const LIB_LIMIT = 20;

function ReadinessBadge({ s }: { s: LibrarySpectrum }) {
  if (s.publish_ready) return <Badge variant="success">Ready</Badge>;
  const blocked = /block|fail|reject/i.test(s.qc_state);
  return (
    <Badge variant={blocked ? "destructive" : "secondary"}>
      {blocked ? "Blocked" : "Needs review"}
    </Badge>
  );
}

function buildLibParams(f: LibFilters): LibraryParams {
  const p: LibraryParams = {};
  if (f.material_type.trim()) p.material_type = f.material_type.trim();
  const nm = Number(f.excitation);
  if (f.excitation.trim() && !Number.isNaN(nm)) p.excitation_wavelength_nm = nm;
  const snr = Number(f.min_snr);
  if (f.min_snr.trim() && !Number.isNaN(snr)) p.min_snr = snr;
  return p;
}

function LibraryTab() {
  const [draft, setDraft] = useState<LibFilters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<LibFilters>(EMPTY_FILTERS);

  const q = useInfiniteQuery({
    queryKey: ["library", applied],
    queryFn: ({ pageParam }) =>
      getMyLibrary({
        ...buildLibParams(applied),
        limit: LIB_LIMIT,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length === LIB_LIMIT ? allPages.length * LIB_LIMIT : undefined,
  });

  const rows: LibrarySpectrum[] = q.data?.pages.flat() ?? [];

  function apply() {
    setApplied(draft);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <Label htmlFor="lib-mat" className="text-xs">
            Material
          </Label>
          <Input
            id="lib-mat"
            value={draft.material_type}
            onChange={(e) =>
              setDraft({ ...draft, material_type: e.target.value })
            }
            className="h-8 w-40"
          />
        </div>
        <div>
          <Label htmlFor="lib-ex" className="text-xs">
            Excitation nm
          </Label>
          <Input
            id="lib-ex"
            type="number"
            value={draft.excitation}
            onChange={(e) => setDraft({ ...draft, excitation: e.target.value })}
            className="h-8 w-28"
          />
        </div>
        <div>
          <Label htmlFor="lib-snr" className="text-xs">
            Min SNR
          </Label>
          <Input
            id="lib-snr"
            type="number"
            value={draft.min_snr}
            onChange={(e) => setDraft({ ...draft, min_snr: e.target.value })}
            className="h-8 w-24"
          />
        </div>
        <Button size="sm" onClick={apply}>
          Apply
        </Button>
      </div>

      {q.isLoading && rows.length === 0 && <Loading />}
      {!q.isLoading && rows.length === 0 && (
        <EmptyState>No spectra match those filters.</EmptyState>
      )}

      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-muted-foreground text-left text-xs">
              <tr>
                <th className="py-2 pr-3 font-medium">Title</th>
                <th className="py-2 pr-3 font-medium">Material</th>
                <th className="py-2 pr-3 font-medium">Excitation</th>
                <th className="py-2 pr-3 font-medium">SNR</th>
                <th className="py-2 pr-3 font-medium">Readiness</th>
                <th className="py-2 pr-3 font-medium">Modality</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="border-border border-t">
                  <td className="py-2 pr-3">{s.title ?? "Untitled"}</td>
                  <td className="py-2 pr-3">{s.material_type ?? "—"}</td>
                  <td className="py-2 pr-3">
                    {s.excitation_wavelength_nm != null
                      ? `${s.excitation_wavelength_nm} nm`
                      : "—"}
                  </td>
                  <td className="py-2 pr-3">
                    {s.snr != null ? Math.round(s.snr) : "—"}
                  </td>
                  <td className="py-2 pr-3">
                    <ReadinessBadge s={s} />
                  </td>
                  <td className="py-2 pr-3 capitalize">{s.modality}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {q.hasNextPage && (
        <Button
          variant="outline"
          size="sm"
          disabled={q.isFetchingNextPage}
          onClick={() => void q.fetchNextPage()}
        >
          {q.isFetchingNextPage ? "Loading…" : "Load more"}
        </Button>
      )}
    </div>
  );
}

/* --- Workspace ------------------------------------------------------- */

function schemaKeys(schema: Record<string, unknown>): string[] {
  const props = schema.properties;
  if (props && typeof props === "object")
    return Object.keys(props as Record<string, unknown>);
  return Object.keys(schema);
}

function WorkspaceTab() {
  return (
    <div className="space-y-8">
      <AlgorithmCatalogBlock />
      <RoutinesBlock />
    </div>
  );
}

function AlgorithmCatalogBlock() {
  const cat = useQuery({
    queryKey: ["algorithms"],
    queryFn: () => getAlgorithmCatalog(),
  });

  if (cat.isLoading) return <Loading />;
  if (!cat.data) return null;

  const { categories, algorithms } = cat.data;

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">Algorithm catalog</h3>
      <div className="space-y-4">
        {categories.map((c) => {
          const algs = algorithms.filter((a) => a.category === c);
          if (algs.length === 0) return null;
          return (
            <div key={c}>
              <p className="text-muted-foreground text-xs font-medium uppercase">
                {c}
              </p>
              <div className="mt-1 space-y-1">
                {algs.map((a) => (
                  <details
                    key={a.step_type}
                    className="border-border rounded-lg border p-2 text-sm"
                  >
                    <summary className="cursor-pointer font-medium">
                      {a.label}
                    </summary>
                    <p className="text-muted-foreground mt-1">{a.description}</p>
                    <p className="mt-1 font-mono text-xs">{a.step_type}</p>
                    {schemaKeys(a.param_schema).length > 0 && (
                      <p className="text-muted-foreground mt-1 text-xs">
                        Params: {schemaKeys(a.param_schema).join(", ")}
                      </p>
                    )}
                  </details>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RoutinesBlock() {
  const qc = useQueryClient();
  const routines = useQuery({
    queryKey: ["routines"],
    queryFn: () => listRoutines(),
  });
  const catalog = useQuery({
    queryKey: ["algorithms"],
    queryFn: () => getAlgorithmCatalog(),
  });

  const [name, setName] = useState("");
  const [picked, setPicked] = useState<string[]>([]);

  const create = useMutation({
    mutationFn: () =>
      createRoutine({
        modality: "raman",
        name: name.trim(),
        steps_template: picked.map((type, i) => ({
          type,
          params: {},
          order: i,
        })),
      }),
    onSuccess: () => {
      setName("");
      setPicked([]);
      void qc.invalidateQueries({ queryKey: ["routines"] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteRoutine(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["routines"] }),
  });

  const steps = catalog.data?.algorithms ?? [];
  const list = routines.data ?? [];

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">Saved routines</h3>

      {list.length === 0 && !routines.isLoading && (
        <EmptyState>No routines yet.</EmptyState>
      )}

      <ul className="space-y-2">
        {list.map((r) => (
          <li
            key={r.id}
            className="border-border flex items-start justify-between gap-3 rounded-lg border p-3"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium">{r.name}</p>
              <div className="mt-1 flex flex-wrap items-center gap-1">
                {r.steps_template.map((s, i) => (
                  <span
                    key={i}
                    className="text-muted-foreground flex items-center text-xs"
                  >
                    {i > 0 && <span className="mx-1">→</span>}
                    <span className="bg-muted rounded px-1.5 py-0.5">
                      {s.type}
                    </span>
                  </span>
                ))}
              </div>
              <p className="text-muted-foreground mt-1 text-xs">
                {new Date(r.created_at).toLocaleDateString()}
              </p>
            </div>
            <Dialog>
              <DialogTrigger asChild>
                <Button size="sm" variant="ghost" aria-label="Delete routine">
                  ×
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Delete “{r.name}”?</DialogTitle>
                  <DialogDescription>This cannot be undone.</DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <DialogClose asChild>
                    <Button variant="outline" size="sm">
                      Cancel
                    </Button>
                  </DialogClose>
                  <DialogClose asChild>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => remove.mutate(r.id)}
                    >
                      Delete
                    </Button>
                  </DialogClose>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </li>
        ))}
      </ul>

      <div className="border-border mt-4 space-y-2 rounded-lg border p-3">
        <p className="text-sm font-medium">New routine</p>
        <Input
          placeholder="Routine name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="h-8"
        />
        <div className="flex flex-wrap gap-1.5">
          {steps.map((s) => {
            const on = picked.includes(s.step_type);
            return (
              <button
                key={s.step_type}
                type="button"
                onClick={() =>
                  setPicked((p) =>
                    on ? p.filter((x) => x !== s.step_type) : [...p, s.step_type],
                  )
                }
                className={
                  on
                    ? "border-transparent bg-primary text-primary-foreground rounded border px-2 py-0.5 text-xs"
                    : "bg-muted rounded border border-transparent px-2 py-0.5 text-xs"
                }
              >
                {s.label}
              </button>
            );
          })}
        </div>
        {picked.length > 0 && (
          <p className="text-muted-foreground text-xs">
            Order: {picked.join(" → ")}
          </p>
        )}
        <Button
          size="sm"
          disabled={!name.trim() || picked.length === 0 || create.isPending}
          onClick={() => create.mutate()}
        >
          {create.isPending ? "Saving…" : "Create routine"}
        </Button>
      </div>
    </div>
  );
}

/* --- Connections --------------------------------------------------- */

function ConnectionsTab({ handle }: { handle: string }) {
  const followers = useQuery({
    queryKey: ["followers", handle],
    queryFn: () => listFollowers(handle),
  });
  const following = useQuery({
    queryKey: ["following", handle],
    queryFn: () => listFollowing(handle),
  });

  return (
    <div className="grid gap-6 sm:grid-cols-2">
      <FollowColumn
        title="Followers"
        users={followers.data ?? []}
        loading={followers.isLoading}
      />
      <FollowColumn
        title="Following"
        users={following.data ?? []}
        loading={following.isLoading}
      />
    </div>
  );
}

function FollowColumn({
  title,
  users,
  loading,
}: {
  title: string;
  users: FollowUser[];
  loading: boolean;
}) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {loading && <Loading />}
      {!loading && users.length === 0 && <EmptyState>Nobody yet.</EmptyState>}
      <ul className="space-y-2">
        {users.map((u) => (
          <li
            key={u.id}
            className="border-border flex items-center gap-3 rounded-lg border p-2"
          >
            <Avatar className="size-8">
              {u.avatar_url ? <AvatarImage src={u.avatar_url} alt="" /> : null}
              <AvatarFallback className="text-xs">
                {(u.display_name ?? u.handle).slice(0, 2).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {u.display_name ?? `@${u.handle}`}
              </p>
              <Link
                href={`/u/${u.handle}`}
                className="text-muted-foreground text-xs hover:underline"
              >
                @{u.handle}
              </Link>
            </div>
            <FollowButton handle={u.handle} />
          </li>
        ))}
      </ul>
    </div>
  );
}
