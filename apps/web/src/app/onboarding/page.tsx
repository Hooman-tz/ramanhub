"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  checkHandle,
  getSession,
  getSuggestedUsers,
  isApiError,
  submitOnboarding,
  toggleFollow,
} from "@ramanhub/api-client";
import type { HandleAvailability } from "@ramanhub/api-client";

import { Button } from "@ramanhub/ui/button";

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

export default function OnboardingPage() {
  const router = useRouter();
  const qc = useQueryClient();

  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });

  useEffect(() => {
    if (session.isFetched && (!session.data || session.data.is_guest)) {
      router.replace("/login?next=/onboarding");
    }
  }, [session.isFetched, session.data, router]);

  const [handle, setHandle] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [interests, setInterests] = useState<string[]>([]);
  const [interestDraft, setInterestDraft] = useState("");
  const [isPublic, setIsPublic] = useState(true);
  const [followed, setFollowed] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  // Prefill name/handle from the session once it arrives — adjust state during
  // render (the React-recommended pattern) rather than in an effect.
  const [prefilledFor, setPrefilledFor] = useState<string | null>(null);
  if (session.data && session.data.id !== prefilledFor) {
    setPrefilledFor(session.data.id);
    if (session.data.display_name) setDisplayName(session.data.display_name);
    if (session.data.profile_handle) setHandle(session.data.profile_handle);
  }

  const debouncedHandle = useDebounced(handle.trim(), 400);
  const availability = useQuery<HandleAvailability | null>({
    queryKey: ["handle-available", debouncedHandle],
    queryFn: () =>
      debouncedHandle.length >= 3 ? checkHandle(debouncedHandle) : null,
    enabled: debouncedHandle.length >= 3,
  });

  const suggested = useQuery({
    queryKey: ["suggested-users"],
    queryFn: () => getSuggestedUsers(10),
  });

  const followMutation = useMutation({
    mutationFn: (h: string) => toggleFollow(h),
  });

  function toggleSuggested(h: string) {
    setFollowed((f) => ({ ...f, [h]: !f[h] }));
    followMutation.mutate(h, {
      onError: () => setFollowed((f) => ({ ...f, [h]: !f[h] })),
    });
  }

  function addInterest() {
    const v = interestDraft.trim().replace(/^#/, "");
    if (v && !interests.includes(v)) setInterests((i) => [...i, v]);
    setInterestDraft("");
  }

  const handleOk = availability.data?.available === true;
  const canFinish = useMemo(
    () => handleOk && displayName.trim().length > 0,
    [handleOk, displayName],
  );

  const finish = useMutation({
    mutationFn: () =>
      submitOnboarding({
        handle: debouncedHandle,
        display_name: displayName.trim(),
        interests,
        is_profile_public: isPublic,
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["session"] });
      router.push("/");
    },
    onError: (e) =>
      setError(
        isApiError(e) ? e.message : "Could not save — check your details.",
      ),
  });

  if (!session.data || session.data.is_guest) {
    return null;
  }

  return (
    <main className="mx-auto w-full max-w-lg px-4 py-10">
      <h1 className="text-2xl font-bold tracking-tight">
        Set up your profile
      </h1>
      <p className="text-muted-foreground mt-1 text-sm">
        A few details so people can find and follow your work.
      </p>

      {/* Step 1: handle + name */}
      <section className="mt-8 space-y-3">
        <h2 className="text-sm font-semibold">1 · Handle &amp; name</h2>
        <div>
          <label className="text-muted-foreground text-xs" htmlFor="handle">
            Handle
          </label>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-muted-foreground text-sm">@</span>
            <input
              id="handle"
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              placeholder="jane-doe"
              className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm"
            />
          </div>
          {debouncedHandle.length >= 3 && (
            <p
              className={
                handleOk
                  ? "mt-1 text-xs text-emerald-600 dark:text-emerald-400"
                  : "text-destructive mt-1 text-xs"
              }
            >
              {availability.isLoading
                ? "Checking…"
                : handleOk
                  ? `✓ @${availability.data?.normalized} is available`
                  : `✗ ${availability.data?.reason ?? "Not available"}`}
            </p>
          )}
        </div>
        <div>
          <label
            className="text-muted-foreground text-xs"
            htmlFor="display-name"
          >
            Display name
          </label>
          <input
            id="display-name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Jane Doe"
            className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
          />
        </div>
      </section>

      {/* Step 2: interests */}
      <section className="mt-8 space-y-3">
        <h2 className="text-sm font-semibold">2 · Research interests</h2>
        <div className="flex flex-wrap gap-1.5">
          {interests.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() =>
                setInterests((i) => i.filter((x) => x !== t))
              }
              className="bg-muted hover:bg-muted/70 rounded px-2 py-0.5 text-xs"
            >
              #{t} ✕
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={interestDraft}
            onChange={(e) => setInterestDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addInterest();
              }
            }}
            placeholder="e.g. surface-enhanced Raman"
            className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm"
          />
          <Button type="button" variant="outline" size="sm" onClick={addInterest}>
            Add
          </Button>
        </div>
      </section>

      {/* Step 3: follow people */}
      <section className="mt-8 space-y-3">
        <h2 className="text-sm font-semibold">3 · Follow a few people</h2>
        {suggested.isLoading && (
          <p className="text-muted-foreground text-sm">Loading suggestions…</p>
        )}
        <ul className="space-y-2">
          {suggested.data?.map((u) => (
            <li
              key={u.id}
              className="border-border flex items-center gap-3 rounded-lg border p-3"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">
                  {u.display_name ?? `@${u.profile_handle}`}
                </p>
                <p className="text-muted-foreground truncate text-xs">
                  @{u.profile_handle}
                  {u.affiliation ? ` · ${u.affiliation}` : ""} ·{" "}
                  {u.follower_count} followers
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                variant={followed[u.profile_handle] ? "outline" : "default"}
                onClick={() => toggleSuggested(u.profile_handle)}
              >
                {followed[u.profile_handle] ? "Following" : "Follow"}
              </Button>
            </li>
          ))}
        </ul>
      </section>

      <label className="mt-8 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={isPublic}
          onChange={(e) => setIsPublic(e.target.checked)}
        />
        Make my profile public
      </label>

      {error && <p className="text-destructive mt-3 text-sm">{error}</p>}

      <div className="mt-6">
        <Button
          disabled={!canFinish || finish.isPending}
          onClick={() => finish.mutate()}
        >
          {finish.isPending ? "Saving…" : "Finish"}
        </Button>
      </div>
    </main>
  );
}
