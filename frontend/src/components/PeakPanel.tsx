import { useCallback, useEffect, useState } from 'react';
import { detectPeaks, type Peak } from '../api/analysis';
import PeakTable from './PeakTable';
import { Button, Card, Skeleton } from './ui';

interface Props {
  spectrumId: string;
  /** Lifted so the chart can mark the same peaks it's showing a table of. */
  onPeaksChange?: (peaks: Peak[]) => void;
}

/** Peak detection controls + results.
 *
 * Detection runs automatically on mount rather than behind a button: the
 * defaults are noise-aware and work on an arbitrary spectrum, so making the
 * user press "detect" before seeing anything would be friction with no
 * decision attached to it. The controls are there to refine, not to start. */
export default function PeakPanel({ spectrumId, onPeaksChange }: Props) {
  const [peaks, setPeaks] = useState<Peak[]>([]);
  const [prominence, setProminence] = useState(0.05);
  const [noiseMultiple, setNoiseMultiple] = useState(6);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<string>('');

  const run = useCallback(
    (prominenceFraction: number, noise: number) => {
      setLoading(true);
      setError(null);
      detectPeaks(spectrumId, {
        prominence_fraction: prominenceFraction,
        noise_multiple: noise,
      })
        .then((result) => {
          setPeaks(result.peaks);
          setStage(result.stage);
          onPeaksChange?.(result.peaks);
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err)))
        .finally(() => setLoading(false));
    },
    [spectrumId, onPeaksChange],
  );

  useEffect(() => {
    run(prominence, noiseMultiple);
    // Intentionally only on mount / spectrum change: the sliders re-run
    // explicitly via onChangeCommitted below, so that dragging one doesn't
    // fire a request per pixel of travel.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spectrumId]);

  return (
    <Card title="Peaks">
      <p className="hint">
        Bands detected on the {stage || 'current'} spectrum. Thresholded on whichever is
        higher: a fraction of the intensity range, or a multiple of the estimated noise —
        which is what keeps the defaults usable on a noisy acquisition.
      </p>

      <div className="peak-controls">
        <label>
          <span>
            Sensitivity <output>{(prominence * 100).toFixed(1)}%</output>
          </span>
          <input
            type="range"
            min={0.005}
            max={0.4}
            step={0.005}
            value={prominence}
            onChange={(e) => setProminence(Number(e.target.value))}
            onMouseUp={() => run(prominence, noiseMultiple)}
            onTouchEnd={() => run(prominence, noiseMultiple)}
            onKeyUp={() => run(prominence, noiseMultiple)}
          />
        </label>

        <label>
          <span>
            Noise rejection <output>{noiseMultiple}σ</output>
          </span>
          <input
            type="range"
            min={0}
            max={15}
            step={1}
            value={noiseMultiple}
            onChange={(e) => setNoiseMultiple(Number(e.target.value))}
            onMouseUp={() => run(prominence, noiseMultiple)}
            onTouchEnd={() => run(prominence, noiseMultiple)}
            onKeyUp={() => run(prominence, noiseMultiple)}
          />
        </label>

        <Button size="sm" onClick={() => run(prominence, noiseMultiple)} loading={loading}>
          Re-detect
        </Button>
      </div>

      {error && <p className="error">{error}</p>}
      {loading && peaks.length === 0 ? (
        <Skeleton lines={4} />
      ) : (
        <>
          <p className="hint">
            {peaks.length} band{peaks.length === 1 ? '' : 's'} found.
          </p>
          <PeakTable peaks={peaks} />
        </>
      )}
    </Card>
  );
}
