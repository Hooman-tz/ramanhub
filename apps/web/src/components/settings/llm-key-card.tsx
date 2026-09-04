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
      setMsg("Key checked and stored. Model calls now go to your account.");
      setEditing(false);
      resetForm();
      await qc.invalidateQueries({ queryKey: ["llm-key"] });
    },
    onError: (e) => {
      setMsg(null);
      setErr(
        isApiError(e) ? e.message : "Could not store that key. Try again.",
      );
    },
  });

  const remove = useMutation({
    mutationFn: () => deleteLlmKey(),
    onSuccess: async () => {
      setErr(null);
      setMsg("Key forgotten. Model calls are back on the shared free pool.");
      await qc.invalidateQueries({ queryKey: ["llm-key"] });
    },
    onError: (e) => {
      setMsg(null);
      setErr(isApiError(e) ? e.message : "Could not forget that key.");
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
    platform_model,
    platform_model_varies,
  } = status.data;
  const canSave = apiKey.trim().length >= 8 && !!selected && !save.isPending;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Model routing</CardTitle>
        <CardDescription>
          Header parsing, structure detection, abstract summaries, filename
          suggestions and the lab consultant all call a language model. Point
          them at your own key and your data never touches our account — and you
          stop queueing behind everyone else&rsquo;s free-tier quota.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {configured ? (
          <p>
            <span className="font-medium">{provider_label}</span>
            <span className="text-muted-foreground"> · ••••{key_last4}</span>
            {storedModel ? (
              <span className="text-muted-foreground"> · {storedModel}</span>
            ) : null}
          </p>
        ) : (
          <p className="text-muted-foreground">
            Running on the shared free-model pool
            {platform_model ? (
              <>
                {" ("}
                <code className="text-xs">{platform_model}</code>
                {platform_model_varies
                  ? ", a different model each call)"
                  : ")"}
              </>
            ) : null}
            {". Your file headers and questions pass through our account."}
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
                placeholder="Paste it here — you won't see it again"
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
              <Label htmlFor="llm-model">Model</Label>
              <Input
                id="llm-model"
                placeholder={selected?.default_model ?? ""}
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
              <p className="text-muted-foreground text-xs">
                Blank means {selected?.default_model ?? "the provider default"}.
                Whatever you name has to be able to return JSON on request.
              </p>
            </div>

            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={!canSave}>
                {save.isPending ? "Checking the key…" : "Save key"}
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
              The key is spent on one throwaway call before it&rsquo;s stored,
              so anything that fails here failed at the provider, not here.
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
              {configured ? "Swap key" : "Use my own key"}
            </Button>

            {configured ? (
              <Dialog>
                <DialogTrigger asChild>
                  <Button variant="destructive" size="sm">
                    Forget key
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Drop your key?</DialogTitle>
                    <DialogDescription>
                      Model calls fall back to the shared free pool, which means
                      your headers and questions route through our account
                      again. Nothing already parsed changes.
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
                        Forget key
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
