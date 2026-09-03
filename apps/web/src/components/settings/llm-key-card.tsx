"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteLlmKey,
  getLlmKeyStatus,
  isApiError,
  setLlmKey,
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

// Matches the native <select> styling used by the chart plot controls —
// packages/ui has no select primitive, and one field does not justify adding
// a shadcn dependency.
const selectCls =
  "border-input bg-background text-foreground focus-visible:ring-ring/50 focus-visible:border-ring h-9 w-full cursor-pointer rounded-md border px-2 text-sm outline-none focus-visible:ring-[3px] disabled:pointer-events-none disabled:opacity-50";

/**
 * "AI provider" settings: paste a provider key and every LLM-backed feature
 * (ingestion parsing, structure detection, abstract enrichment, filename
 * suggestions, the lab consultant) routes to it instead of RamanHub's shared
 * free models.
 *
 * The key is write-only — the server returns only its last 4 characters — so
 * "replace" is the only edit; there is nothing to pre-fill.
 */
export function LlmKeyCard() {
  const qc = useQueryClient();

  const status = useQuery({
    queryKey: ["llm-key"],
    queryFn: () => getLlmKeyStatus(),
  });

  const [editing, setEditing] = useState(false);
  const [provider, setProvider] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const providers = status.data?.providers ?? [];
  const selected =
    providers.find((p) => p.slug === provider) ?? providers[0] ?? null;

  function resetForm() {
    setProvider("");
    setApiKey("");
    setModel("");
  }

  const save = useMutation({
    mutationFn: () =>
      setLlmKey({
        provider: selected?.slug ?? "",
        api_key: apiKey.trim(),
        model: model.trim() || undefined,
      }),
    onSuccess: async () => {
      setErr(null);
      setMsg("Key saved and verified.");
      setEditing(false);
      resetForm();
      await qc.invalidateQueries({ queryKey: ["llm-key"] });
    },
    onError: (e) => {
      setMsg(null);
      setErr(
        isApiError(e) ? e.message : "Could not save that key — try again.",
      );
    },
  });

  const remove = useMutation({
    mutationFn: () => deleteLlmKey(),
    onSuccess: async () => {
      setErr(null);
      setMsg("Key removed. Back to the shared free models.");
      await qc.invalidateQueries({ queryKey: ["llm-key"] });
    },
    onError: (e) => {
      setMsg(null);
      setErr(isApiError(e) ? e.message : "Could not remove that key.");
    },
  });

  // Not loaded yet, or the deployment has no encryption key configured — in
  // which case there is nothing the user can do here.
  if (!status.data?.enabled) return null;

  const {
    configured,
    provider_label,
    model: storedModel,
    key_last4,
  } = status.data;
  const canSave = apiKey.trim().length >= 8 && !!selected && !save.isPending;

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI provider</CardTitle>
        <CardDescription>
          Use your own provider key so your spectra and questions go to your
          account instead of ours — and so you are not sharing our free-tier
          rate limits.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {configured ? (
          <p>
            {provider_label} · ••••{key_last4}
            {storedModel ? (
              <span className="text-muted-foreground"> · {storedModel}</span>
            ) : null}
          </p>
        ) : (
          <p className="text-muted-foreground">
            Your data is processed using RamanHub&rsquo;s shared free models.
          </p>
        )}

        {editing ? (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="llm-provider">Provider</Label>
              <select
                id="llm-provider"
                className={selectCls}
                value={selected?.slug ?? ""}
                onChange={(e) => setProvider(e.target.value)}
              >
                {providers.map((p) => (
                  <option key={p.slug} value={p.slug}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="llm-key">API key</Label>
              <Input
                id="llm-key"
                type="password"
                autoComplete="off"
                placeholder="Paste your key"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              {selected ? (
                <p className="text-muted-foreground text-xs">
                  {selected.key_hint}
                </p>
              ) : null}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="llm-model">Model (optional)</Label>
              <Input
                id="llm-model"
                placeholder={selected?.default_model ?? ""}
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </div>

            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={!canSave}>
                {save.isPending ? "Verifying…" : "Save key"}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setEditing(false);
                  resetForm();
                  setErr(null);
                }}
              >
                Cancel
              </Button>
            </div>
            <p className="text-muted-foreground text-xs">
              We check the key against the provider before saving it, so an
              error here means the key itself was rejected.
            </p>
          </form>
        ) : (
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setEditing(true);
                setMsg(null);
                setErr(null);
              }}
            >
              {configured ? "Replace key" : "Use my own key"}
            </Button>

            {configured ? (
              <Dialog>
                <DialogTrigger asChild>
                  <Button variant="destructive" size="sm">
                    Remove key
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Remove your API key?</DialogTitle>
                    <DialogDescription>
                      AI features will go back to RamanHub&rsquo;s shared free
                      models, which means your data is processed on our account
                      again.
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
                        disabled={remove.isPending}
                        onClick={() => remove.mutate()}
                      >
                        Remove key
                      </Button>
                    </DialogClose>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            ) : null}
          </div>
        )}

        {msg ? <p className="text-muted-foreground text-xs">{msg}</p> : null}
        {err ? <p className="text-destructive text-xs">{err}</p> : null}
      </CardContent>
    </Card>
  );
}
