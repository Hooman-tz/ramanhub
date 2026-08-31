import Link from "next/link";
import { BadgeCheck } from "lucide-react";

import type { PublicProfile } from "@ramanhub/api-client";
import { Avatar, AvatarFallback, AvatarImage } from "@ramanhub/ui/avatar";
import { Badge } from "@ramanhub/ui/badge";
import { Button } from "@ramanhub/ui/button";
import { Card } from "@ramanhub/ui/card";

import { FollowButton } from "~/components/follow-button";

function initials(name: string | null, handle: string): string {
  const source = (name?.trim() ?? handle).trim();
  if (!source) return "?";
  const parts = source.split(/\s+/).filter(Boolean);
  const first = parts[0] ?? source;
  const second = parts[1];
  const letters = second
    ? first.slice(0, 1) + second.slice(0, 1)
    : source.slice(0, 2);
  return letters.toUpperCase();
}

export function ProfileHeader({
  profile,
  isOwner,
}: {
  profile: PublicProfile;
  isOwner: boolean;
}) {
  const handle = profile.profile_handle ?? "";
  const name = profile.display_name ?? `@${handle}`;

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="from-primary/25 to-primary/5 h-24 bg-gradient-to-r sm:h-32" />
      <div className="px-6 pb-6">
        <div className="-mt-10 flex items-end justify-between sm:-mt-12">
          <Avatar className="border-background size-20 border-4 sm:size-24">
            {profile.avatar_url ? (
              <AvatarImage src={profile.avatar_url} alt={name} />
            ) : null}
            <AvatarFallback className="text-lg font-semibold">
              {initials(profile.display_name, handle)}
            </AvatarFallback>
          </Avatar>

          <div className="mb-1">
            {isOwner ? (
              <Link href="/settings">
                <Button size="sm" variant="outline">
                  Edit profile
                </Button>
              </Link>
            ) : (
              <FollowButton handle={handle} />
            )}
          </div>
        </div>

        <div className="mt-3">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-bold">{name}</h1>
            {profile.orcid_verified && (
              <Badge variant="success" asChild>
                <a
                  href={`https://orcid.org/${profile.orcid_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none"
                >
                  <BadgeCheck className="size-3" aria-hidden />
                  ORCID verified
                </a>
              </Badge>
            )}
          </div>
          <p className="text-foreground/70 text-sm">@{handle}</p>
          {profile.affiliation && (
            <p className="text-foreground/80 mt-1 text-sm">
              {profile.affiliation}
            </p>
          )}
          {profile.bio && (
            <p className="text-foreground/90 mt-2 max-w-prose text-sm whitespace-pre-wrap">
              {profile.bio}
            </p>
          )}

          {profile.research_interests &&
            profile.research_interests.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {profile.research_interests.map((t) => (
                  <Badge key={t} variant="secondary">
                    {t}
                  </Badge>
                ))}
              </div>
            )}

          <div className="text-foreground/70 mt-4 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            <span>
              <strong className="text-foreground">
                {profile.finding_count}
              </strong>{" "}
              posts
            </span>
            <span>
              <strong className="text-foreground">
                {profile.spectrum_count}
              </strong>{" "}
              spectra
            </span>
            <Link
              href={`/u/${handle}?tab=connections`}
              className="hover:text-foreground focus-visible:ring-ring/50 rounded transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
            >
              <strong className="text-foreground">{profile.followers}</strong>{" "}
              followers
            </Link>
            <Link
              href={`/u/${handle}?tab=connections`}
              className="hover:text-foreground focus-visible:ring-ring/50 rounded transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
            >
              <strong className="text-foreground">{profile.following}</strong>{" "}
              following
            </Link>
          </div>
        </div>
      </div>
    </Card>
  );
}
