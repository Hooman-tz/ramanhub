import { useEffect, useMemo, useState } from 'react';
import { getActivity, type ActivityDay, type ActivitySummary } from '../api/client';
import { Skeleton } from './ui';

/** Colour steps. Four rather than GitHub's five: with a corpus this size the
 * fifth bucket almost never fills, and an unused step just makes the legend
 * lie about the scale. */
const LEVELS = 4;

function levelFor(total: number, busiest: number): number {
  if (total <= 0) return 0;
  if (busiest <= 1) return 1;
  // Square-root rather than linear: a 40-spectrum instrument session would
  // otherwise flatten every ordinary day to the palest step. The same
  // compression instinct as the log() in the backend's ranking.
  const ratio = Math.sqrt(total) / Math.sqrt(busiest);
  return Math.max(1, Math.min(LEVELS, Math.ceil(ratio * LEVELS)));
}

function describe(day: ActivityDay): string {
  const parts: string[] = [];
  if (day.spectra) parts.push(`${day.spectra} spectra`);
  if (day.findings) parts.push(`${day.findings} finding${day.findings === 1 ? '' : 's'}`);
  if (day.comments) parts.push(`${day.comments} comment${day.comments === 1 ? '' : 's'}`);
  const when = new Date(`${day.date}T00:00:00`).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
  return parts.length ? `${when}: ${parts.join(', ')}` : `${when}: nothing published`;
}

/** Contribution activity over the last year, plus streaks.
 *
 * Kinds are kept visually distinct in the tooltip rather than summed into one
 * number: publishing a Finding, publishing a spectrum and writing a comment
 * are different acts with different costs, and a single blended count tells
 * you which happened only by accident. */
export default function ContributionChart({ handle }: { handle: string }) {
  const [summary, setSummary] = useState<ActivitySummary | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getActivity(handle, 365)
      .then((s) => !cancelled && setSummary(s))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [handle]);

  const weeks = useMemo(() => {
    if (!summary) return [];
    const days = summary.days;
    // Pad the front so every column is a full week and rows line up with
    // weekdays — an unpadded grid shifts the whole calendar by a day or two
    // and the columns stop meaning anything.
    const firstWeekday = new Date(`${days[0].date}T00:00:00`).getDay();
    const padded: (ActivityDay | null)[] = [...Array(firstWeekday).fill(null), ...days];
    const out: (ActivityDay | null)[][] = [];
    for (let i = 0; i < padded.length; i += 7) out.push(padded.slice(i, i + 7));
    return out;
  }, [summary]);

  // A failed activity fetch must not take the profile down with it — the
  // chart is context, not the content.
  if (failed) return null;
  if (!summary) return <Skeleton lines={2} height="3rem" />;

  const busiest = Math.max(
    1,
    ...summary.days.map((d) => d.spectra + d.findings + d.comments),
  );

  return (
    <section className="contrib" aria-label="Contribution activity">
      <header className="contrib__head">
        <span className="hint">
          {summary.total} contribution{summary.total === 1 ? '' : 's'} in the last year
        </span>
        <span className="contrib__streaks">
          <strong>{summary.current_streak}</strong> day current streak ·{' '}
          <strong>{summary.longest_streak}</strong> longest
        </span>
      </header>

      <div className="contrib__grid" role="img" aria-label={`${summary.total} contributions in the last year`}>
        {weeks.map((week, wi) => (
          <div key={wi} className="contrib__week">
            {week.map((day, di) =>
              day === null ? (
                <span key={di} className="contrib__cell contrib__cell--pad" />
              ) : (
                <span
                  key={day.date}
                  className={`contrib__cell contrib__cell--l${levelFor(
                    day.spectra + day.findings + day.comments,
                    busiest,
                  )}`}
                  title={describe(day)}
                />
              ),
            )}
          </div>
        ))}
      </div>

      <div className="contrib__legend">
        <span className="hint">Less</span>
        {Array.from({ length: LEVELS + 1 }, (_, i) => (
          <span key={i} className={`contrib__cell contrib__cell--l${i}`} />
        ))}
        <span className="hint">More</span>
      </div>
    </section>
  );
}
