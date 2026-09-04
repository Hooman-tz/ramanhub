"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";

import type { HandleAvailability } from "@ramanhub/api-client";
import {
  checkHandle,
  getSession,
  getSuggestedUsers,
  isApiError,
  submitOnboarding,
  toggleFollow,
} from "@ramanhub/api-client";
import { Button } from "@ramanhub/ui/button";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { useDebounced } from "~/hooks/use-debounced";

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
      <h1 className="text-2xl font-bold tracking-tight">Set up your profile</h1>
      <p className="text-foreground/80 mt-1 text-sm">
        A few details so people can find and follow your work.
      </p>

      {/* Step 1: handle + name */}
      <section className="mt-8 space-y-4">
        <h2 className="text-base font-semibold tracking-tight">
          1 · Handle &amp; name
        </h2>
        <div className="space-y-1.5">
          <label
            className="text-foreground text-sm font-medium"
            htmlFor="handle"
          >
            Handle
          </label>
          <div className="flex items-center gap-2">
            <span className="text-foreground/70 text-sm">@</span>
            <input
              id="handle"
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              placeholder="jane-doe"
              className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm focus-visible:ring-[3px] focus-visible:outline-none"
            />
          </div>
          {debouncedHandle.length >= 3 && (
            <p
              className={
                handleOk
                  ? "inline-flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-400"
                  : "text-destructive inline-flex items-center gap-1 text-xs"
              }
            >
              {availability.isLoading ? (
                "Checking…"
              ) : handleOk ? (
                <>
                  <Check className="size-3.5" aria-hidden />@
                  {availability.data?.normalized} is available
                </>
              ) : (
                <>
                  <X className="size-3.5" aria-hidden />
                  {availability.data?.reason ?? "Not available"}
                </>
              )}
            </p>
          )}
        </div>
        <div className="space-y-1.5">
          <label
            className="text-foreground text-sm font-medium"
            htmlFor="display-name"
          >
            Display name
          </label>
          <input
            id="display-name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Jane Doe"
            className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm focus-visible:ring-[3px] focus-visible:outline-none"
          />
        </div>
      </section>

      {/* Step 2: interests */}
      <section className="mt-8 space-y-4">
        <h2 className="text-base font-semibold tracking-tight">
          2 · Research interests
        </h2>
        <div className="flex flex-wrap gap-1.5">
          {interests.map((t) => (
            <button
              key={t}
              type="button"
              aria-label={`Remove ${t}`}
              onClick={() => setInterests((i) => i.filter((x) => x !== t))}
              className="bg-muted text-foreground/80 hover:bg-muted/70 focus-visible:ring-ring/50 inline-flex min-h-8 cursor-pointer items-center gap-1 rounded px-2 text-xs transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
            >
              #{t}
              <X className="size-3" aria-hidden />
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
            aria-label="Add a research interest"
            className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm focus-visible:ring-[3px] focus-visible:outline-none"
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addInterest}
          >
            Add
          </Button>
        </div>
      </section>

      {/* Step 3: follow people */}
      <section className="mt-8 space-y-4">
        <h2 className="text-base font-semibold tracking-tight">
          3 · Follow a few people
        </h2>
        {suggested.isLoading && (
          <div className="space-y-2" aria-hidden>
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-16 w-full rounded-lg" />
            ))}
          </div>
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
                <p className="text-foreground/70 truncate text-xs">
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

      <label className="mt-8 flex cursor-pointer items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={isPublic}
          onChange={(e) => setIsPublic(e.target.checked)}
          className="accent-primary focus-visible:ring-ring/50 size-4 cursor-pointer rounded focus-visible:ring-[3px] focus-visible:outline-none"
        />
        Make my profile public
      </label>

      {error && (
        <p className="text-destructive mt-3 text-sm" role="alert">
          {error}
        </p>
      )}

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
