"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";

import {
  deleteMe,
  exportMe,
  getSession,
  getUserByHandle,
  isApiError,
  updateMe,
} from "@ramanhub/api-client";
import { Button } from "@ramanhub/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@ramanhub/ui/card";
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

import { LlmKeyCard } from "~/components/settings/llm-key-card";

interface ProfileForm {
  display_name: string;
  affiliation: string;
  bio: string;
  is_profile_public: boolean;
}

const BLANK: ProfileForm = {
  display_name: "",
  affiliation: "",
  bio: "",
  is_profile_public: true,
};

export default function SettingsPage() {
  const router = useRouter();
  const qc = useQueryClient();

  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });

  useEffect(() => {
    if (session.isFetched && (!session.data || session.data.is_guest)) {
      router.replace("/login?next=/settings");
    }
  }, [session.isFetched, session.data, router]);

  const currentHandle = session.data?.profile_handle ?? null;

  const profile = useQuery({
    queryKey: ["profile", currentHandle],
    queryFn: () => getUserByHandle(currentHandle ?? ""),
    enabled: !!currentHandle,
  });

  const [form, setForm] = useState<ProfileForm>(BLANK);
  const [interests, setInterests] = useState<string[]>([]);
  const [interestDraft, setInterestDraft] = useState("");
  const [hydratedFor, setHydratedFor] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  // Hydrate the form once per signed-in user, after the public profile (which
  // carries bio/affiliation/interests — the session payload does not) resolves.
  const uid = session.data?.id ?? null;
  if (
    uid &&
    hydratedFor !== uid &&
    session.data &&
    (!currentHandle || profile.isFetched)
  ) {
    setHydratedFor(uid);
    setForm({
      display_name: session.data.display_name ?? "",
      affiliation: profile.data?.affiliation ?? "",
      bio: profile.data?.bio ?? "",
      is_profile_public: session.data.is_profile_public ?? true,
    });
    setInterests(profile.data?.research_interests ?? []);
  }

  const save = useMutation({
    mutationFn: () =>
      updateMe({
        display_name: form.display_name.trim() || undefined,
        affiliation: form.affiliation.trim(),
        bio: form.bio.trim(),
        research_interests: interests,
        is_profile_public: form.is_profile_public,
      }),
    onSuccess: async () => {
      setErr(null);
      setMsg("Saved.");
      await qc.invalidateQueries({ queryKey: ["session"] });
      await qc.invalidateQueries({ queryKey: ["profile"] });
    },
    onError: (e) => {
      setMsg(null);
      setErr(isApiError(e) ? e.message : "Could not save your changes.");
    },
  });

  const del = useMutation({
    mutationFn: () => deleteMe(),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["session"] });
      router.push("/");
    },
  });

  function addInterest() {
    const v = interestDraft.trim().replace(/^#/, "");
    if (v && !interests.includes(v)) setInterests((i) => [...i, v]);
    setInterestDraft("");
  }

  async function downloadExport() {
    setExporting(true);
    setErr(null);
    try {
      const data = await exportMe();
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "ramanhub-account-export.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setErr("Could not export your data — try again.");
    } finally {
      setExporting(false);
    }
  }

  if (!session.data || session.data.is_guest) return null;

  const canSave = form.display_name.trim().length > 0 && !save.isPending;

  return (
    <main className="mx-auto w-full max-w-lg space-y-6 px-4 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Settings</h1>

      {/* Profile */}
      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>
            How your work is credited across the platform.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="display_name">Display name</Label>
              <Input
                id="display_name"
                value={form.display_name}
                onChange={(e) =>
                  setForm({ ...form, display_name: e.target.value })
                }
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="handle">Handle</Label>
              <Input
                id="handle"
                value={currentHandle ? `@${currentHandle}` : "—"}
                readOnly
                disabled
                className="opacity-70"
              />
              <p className="text-muted-foreground text-xs">
                Your handle is permanent — it&apos;s how your work is cited and
                linked. Contact support if it must change.
              </p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="affiliation">Affiliation</Label>
              <Input
                id="affiliation"
                value={form.affiliation}
                onChange={(e) =>
                  setForm({ ...form, affiliation: e.target.value })
                }
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="bio">Bio</Label>
              <textarea
                id="bio"
                rows={4}
                value={form.bio}
                onChange={(e) => setForm({ ...form, bio: e.target.value })}
                className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm leading-relaxed focus-visible:ring-[3px] focus-visible:outline-none"
              />
            </div>

            <div className="space-y-1.5">
              <Label>Research interests</Label>
              <div className="flex flex-wrap gap-1.5">
                {interests.map((t) => (
                  <button
                    key={t}
                    type="button"
                    aria-label={`Remove ${t}`}
                    onClick={() =>
                      setInterests((i) => i.filter((x) => x !== t))
                    }
                    className="bg-muted text-foreground/80 hover:bg-muted/70 focus-visible:ring-ring/50 inline-flex min-h-8 cursor-pointer items-center gap-1 rounded px-2 text-xs transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
                  >
                    {t}
                    <X className="size-3" aria-hidden />
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <Input
                  value={interestDraft}
                  onChange={(e) => setInterestDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addInterest();
                    }
                  }}
                  placeholder="e.g. surface-enhanced Raman"
                  className="h-8"
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
            </div>

            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.is_profile_public}
                onChange={(e) =>
                  setForm({ ...form, is_profile_public: e.target.checked })
                }
                className="accent-primary focus-visible:ring-ring/50 size-4 cursor-pointer rounded focus-visible:ring-[3px] focus-visible:outline-none"
              />
              Make my profile public
            </label>

            {msg && (
              <p className="text-xs text-emerald-600 dark:text-emerald-400">
                {msg}
              </p>
            )}
            {err && <p className="text-destructive text-xs">{err}</p>}

            <Button type="submit" disabled={!canSave}>
              {save.isPending ? "Saving…" : "Save changes"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Identity */}
      <Card>
        <CardHeader>
          <CardTitle>Identity</CardTitle>
          <CardDescription>
            Link your ORCID iD to show a verified badge on your profile.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {session.data.orcid_id ? (
            <p>
              ORCID iD:{" "}
              <a
                href={`https://orcid.org/${session.data.orcid_id}`}
                target="_blank"
                rel="noreferrer"
                className="text-primary hover:underline"
              >
                {session.data.orcid_id}
              </a>{" "}
              <span className="text-muted-foreground">
                {profile.data?.orcid_verified ? "· verified" : "· not verified"}
              </span>
            </p>
          ) : (
            <p className="text-muted-foreground">No ORCID iD linked yet.</p>
          )}
          <a href="/api/users/me/orcid/link">
            <Button variant="outline" size="sm">
              {session.data.orcid_id ? "Re-link ORCID" : "Link ORCID"}
            </Button>
          </a>
        </CardContent>
      </Card>

      <LlmKeyCard />

      {/* Data */}
      <Card>
        <CardHeader>
          <CardTitle>Data</CardTitle>
          <CardDescription>
            Export or permanently close your account.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button
            variant="outline"
            size="sm"
            disabled={exporting}
            onClick={downloadExport}
          >
            {exporting ? "Preparing…" : "Download my data"}
          </Button>

          <div>
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="destructive" size="sm">
                  Delete account
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Delete your account?</DialogTitle>
                  <DialogDescription>
                    Your profile is anonymized. Published scientific records
                    stay for provenance, but this cannot be undone.
                  </DialogDescription>
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
                      disabled={del.isPending}
                      onClick={() => del.mutate()}
                    >
                      Delete account
                    </Button>
                  </DialogClose>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
