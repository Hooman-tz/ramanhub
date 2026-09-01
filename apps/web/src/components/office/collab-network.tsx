"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useQueries } from "@tanstack/react-query";

import type { FollowUser } from "@ramanhub/api-client";
import { listFollowers, listFollowing } from "@ramanhub/api-client";
import { Card } from "@ramanhub/ui/card";
import { Skeleton } from "@ramanhub/ui/skeleton";

function shortName(u: FollowUser): string {
  const n = u.display_name ?? u.handle;
  const parts = n.split(/\s+/).filter(Boolean);
  return parts[parts.length - 1] ?? n;
}

function initials(u: FollowUser): string {
  const n = u.display_name ?? u.handle;
  return n
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

/**
 * A light collaboration graph: "you" at the centre, the people you follow
 * around a ring, edges thickened for mutuals (they follow you back).
 * Purely derived from the real follow graph.
 */
export function CollabNetwork({ handle }: { handle: string }) {
  const [following, followers] = useQueries({
    queries: [
      {
        queryKey: ["following", handle],
        queryFn: () => listFollowing(handle, { limit: 12 }),
      },
      {
        queryKey: ["followers", handle],
        queryFn: () => listFollowers(handle, { limit: 100 }),
      },
    ],
  });

  const loading = following.isLoading || followers.isLoading;
  const followerIds = useMemo(
    () => new Set((followers.data ?? []).map((u) => u.id)),
    [followers.data],
  );
  const nodes = useMemo(() => following.data ?? [], [following.data]);

  const layout = useMemo(() => {
    const cx = 210;
    const cy = 150;
    const r = 110;
    return nodes.map((u, i) => {
      const a = (i / Math.max(1, nodes.length)) * Math.PI * 2 - Math.PI / 2;
      return {
        u,
        x: cx + r * Math.cos(a),
        y: cy + r * Math.sin(a),
        mutual: followerIds.has(u.id),
      };
    });
  }, [nodes, followerIds]);

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="border-border flex items-center justify-between border-b px-5 py-3.5">
        <div className="text-sm font-semibold">Collaboration network</div>
        <div className="text-muted-foreground text-xs">
          {nodes.length} following
        </div>
      </div>

      {loading ? (
        <Skeleton className="m-4 h-56" />
      ) : nodes.length < 2 ? (
        <p className="text-muted-foreground p-6 text-center text-xs">
          Follow a few researchers to see your network here.
        </p>
      ) : (
        <>
          <div className="p-4">
            <svg
              viewBox="0 0 420 300"
              className="max-h-64 w-full"
              role="img"
              aria-label={`Network of ${nodes.length} researchers you follow`}
            >
              {layout.map((n) => (
                <line
                  key={`e-${n.u.id}`}
                  x1={210}
                  y1={150}
                  x2={n.x}
                  y2={n.y}
                  className="stroke-border"
                  strokeWidth={n.mutual ? 2.4 : 1.2}
                />
              ))}
              {layout.map((n) => (
                <g key={`n-${n.u.id}`}>
                  <circle
                    cx={n.x}
                    cy={n.y}
                    r={n.mutual ? 15 : 12}
                    className={
                      n.mutual ? "fill-primary/80" : "fill-muted-foreground/60"
                    }
                    stroke="white"
                    strokeWidth={2}
                  />
                  <text
                    x={n.x}
                    y={n.y + 28}
                    textAnchor="middle"
                    className="fill-muted-foreground text-[9px]"
                  >
                    {shortName(n.u)}
                  </text>
                </g>
              ))}
              <circle
                cx={210}
                cy={150}
                r={22}
                className="fill-primary"
                stroke="white"
                strokeWidth={3}
              />
              <text
                x={210}
                y={154}
                textAnchor="middle"
                className="fill-primary-foreground text-[10px] font-bold"
              >
                You
              </text>
            </svg>
          </div>
          <div className="divide-border border-border divide-y border-t">
            {nodes.map((u) => (
              <Link
                key={u.id}
                href={`/u/${u.handle}`}
                className="hover:bg-secondary/30 flex items-center gap-3 px-5 py-2.5 transition-colors"
              >
                <span className="bg-muted-foreground/60 flex size-6 shrink-0 items-center justify-center rounded-full text-[9px] font-bold text-white">
                  {initials(u)}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-medium">
                    {u.display_name ?? `@${u.handle}`}
                  </div>
                  {u.affiliation && (
                    <div className="text-muted-foreground truncate text-[10px]">
                      {u.affiliation}
                    </div>
                  )}
                </div>
                {followerIds.has(u.id) && (
                  <span className="text-primary shrink-0 text-[10px] font-medium">
                    mutual
                  </span>
                )}
              </Link>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}
