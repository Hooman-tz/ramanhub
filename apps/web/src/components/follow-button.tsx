"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getFollowStatus,
  getSession,
  toggleFollow,
} from "@ramanhub/api-client";
import type { FollowStatus } from "@ramanhub/api-client";

import { Button } from "@ramanhub/ui/button";

export function FollowButton({
  handle,
  initial,
}: {
  handle: string;
  initial?: FollowStatus;
}) {
  const qc = useQueryClient();

  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });

  const status = useQuery({
    queryKey: ["follow", handle],
    queryFn: () => getFollowStatus(handle),
    initialData: initial,
  });

  const mutation = useMutation({
    mutationFn: () => toggleFollow(handle),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ["follow", handle] });
      const prev = qc.getQueryData<FollowStatus>(["follow", handle]);
      if (prev) {
        qc.setQueryData<FollowStatus>(["follow", handle], {
          following: !prev.following,
          follower_count: prev.follower_count + (prev.following ? -1 : 1),
        });
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["follow", handle], ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["follow", handle] });
      void qc.invalidateQueries({ queryKey: ["feed", "following"] });
    },
  });

  const signedIn = !!session.data && !session.data.is_guest;

  if (session.isFetched && !signedIn) {
    return (
      <Link href={`/login?next=/u/${handle}`}>
        <Button size="sm" variant="outline">
          Follow
        </Button>
      </Link>
    );
  }

  const following = status.data?.following ?? false;

  return (
    <Button
      size="sm"
      variant={following ? "outline" : "default"}
      disabled={mutation.isPending || status.isLoading}
      onClick={() => mutation.mutate()}
    >
      {following ? "Following" : "Follow"}
    </Button>
  );
}
