"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import type { ActivityDay } from "@ramanhub/api-client";
import { getUserActivity } from "@ramanhub/api-client";
import { Card } from "@ramanhub/ui/card";
import { Skeleton } from "@ramanhub/ui/skeleton";

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** 0 → muted, then chart-5 (lightest) … chart-1 (darkest). */
function levelClass(count: number): string {
  if (count <= 0) return "bg-muted";
  if (count <= 2) return "bg-chart-5";
  if (count <= 4) return "bg-chart-4";
  if (count <= 6) return "bg-chart-3";
  if (count <= 9) return "bg-chart-2";
  return "bg-chart-1";
}

function total(day: ActivityDay): number {
  return day.spectra + day.findings + day.comments;
}

export function ContributionGraph({ handle }: { handle: string }) {
  const activity = useQuery({
    queryKey: ["activity", handle],
    queryFn: () => getUserActivity(handle, 365),
  });

  const weeks = useMemo(() => {
    const days = activity.data?.days ?? [];
    const firstDay = days[0];
    if (!firstDay) return [] as (ActivityDay | null)[][];
    const cells: (ActivityDay | null)[] = [];
    const first = new Date(`${firstDay.date}T00:00:00Z`);
    const leading = first.getUTCDay();
    for (let i = 0; i < leading; i++) cells.push(null);
    for (const d of days) cells.push(d);
    while (cells.length % 7 !== 0) cells.push(null);
    const out: (ActivityDay | null)[][] = [];
    for (let i = 0; i < cells.length; i += 7) out.push(cells.slice(i, i + 7));
    return out;
  }, [activity.data]);

  if (activity.isLoading) {
    return (
      <Card className="p-4">
        <Skeleton className="h-4 w-56" />
        <Skeleton className="mt-3 h-24 w-full" />
      </Card>
    );
  }

  if (activity.isError || !activity.data) {
    return null;
  }

  const { total: totalCount, current_streak, longest_streak } = activity.data;

  let lastMonth = -1;

  return (
    <Card className="gap-3 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold tracking-tight">
          {totalCount} contribution{totalCount === 1 ? "" : "s"} in the last
          year
        </h2>
        <p className="text-foreground/70 text-xs">
          Current streak{" "}
          <strong className="text-foreground">{current_streak}</strong> ·
          Longest <strong className="text-foreground">{longest_streak}</strong>
        </p>
      </div>

      <div className="overflow-x-auto">
        <div className="inline-flex flex-col gap-1">
          <div className="text-muted-foreground flex gap-[3px] text-[0.6rem]">
            {weeks.map((week, wi) => {
              const firstDay = week.find((d) => d != null);
              const month = firstDay
                ? new Date(`${firstDay.date}T00:00:00Z`).getUTCMonth()
                : -1;
              const show = month !== -1 && month !== lastMonth;
              if (show) lastMonth = month;
              return (
                <span
                  key={wi}
                  className="w-[11px] shrink-0"
                  style={{ minWidth: 11 }}
                >
                  {show ? (MONTHS[month] ?? "") : ""}
                </span>
              );
            })}
          </div>
          <div className="flex gap-[3px]">
            {weeks.map((week, wi) => (
              <div key={wi} className="flex flex-col gap-[3px]">
                {week.map((day, di) => (
                  <div
                    key={di}
                    className={`size-[11px] rounded-[2px] ${
                      day ? levelClass(total(day)) : "bg-transparent"
                    }`}
                    title={
                      day
                        ? `${total(day)} contribution${
                            total(day) === 1 ? "" : "s"
                          } on ${day.date}`
                        : undefined
                    }
                  />
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="text-foreground/70 flex items-center gap-1 text-[0.65rem]">
        <span>Less</span>
        <span className="bg-muted size-[11px] rounded-[2px]" />
        <span className="bg-chart-5 size-[11px] rounded-[2px]" />
        <span className="bg-chart-4 size-[11px] rounded-[2px]" />
        <span className="bg-chart-3 size-[11px] rounded-[2px]" />
        <span className="bg-chart-2 size-[11px] rounded-[2px]" />
        <span className="bg-chart-1 size-[11px] rounded-[2px]" />
        <span>More</span>
      </div>
    </Card>
  );
}
