"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addPin, getSession, getUserPins, removePin } from "@ramanhub/api-client";

import { Button } from "@ramanhub/ui/button";

const MAX_PINS = 4;

/**
 * "Pin to profile" toggle for the owner of a finding / spectrum. Reads the
 * owner's own pin list (public endpoint) to know current state + the 4-slot
 * limit, and writes through `POST /pins` / `DELETE /pins/{kind}/{id}`.
 */
export function PinButton({
  kind,
  id,
}: {
  kind: "finding" | "spectrum";
  id: string;
}) {
  const qc = useQueryClient();

  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });
  const handle = session.data?.profile_handle ?? null;

  const pins = useQuery({
    queryKey: ["pins", handle],
    queryFn: () => getUserPins(handle ?? ""),
    enabled: !!handle,
  });

  const list = pins.data ?? [];
  const pinned = list.some((p) => p.kind === kind && p.id === id);
  const atLimit = list.length >= MAX_PINS && !pinned;

  const toggle = useMutation({
    mutationFn: () =>
      pinned ? removePin(kind, id) : addPin({ kind, id }),
    onSuccess: (next) => {
      if (handle) qc.setQueryData(["pins", handle], next);
    },
  });

  if (!handle) return null;

  return (
    <Button
      size="sm"
      variant={pinned ? "outline" : "secondary"}
      disabled={toggle.isPending || atLimit || pins.isLoading}
      onClick={() => toggle.mutate()}
    >
      {pinned
        ? "Pinned to profile"
        : atLimit
          ? "Pin limit reached (4)"
          : "Pin to profile"}
    </Button>
  );
}
