"use client";

import { cn } from "@ramanhub/ui";
import { Button } from "@ramanhub/ui/button";
import { Input } from "@ramanhub/ui/input";

import type { SpectrumDisplayOptions } from "./spectrum-chart";
import { DEFAULT_DISPLAY_OPTIONS } from "./spectrum-chart";

// Re-exported here so the lab can pull the chart's view-option contract and its
// controls from a single module.
export { DEFAULT_DISPLAY_OPTIONS };
export type { SpectrumDisplayOptions };

type NormalizeMode = NonNullable<SpectrumDisplayOptions["normalize"]>;

const NORMALIZE_OPTIONS: { value: NormalizeMode; label: string }[] = [
  { value: "none", label: "Raw" },
  { value: "max", label: "Max = 1" },
  { value: "minmax", label: "Min–max" },
  { value: "area", label: "Area = 1" },
];

export interface PlotControlsProps {
  /** Current view options (controlled). */
  value: SpectrumDisplayOptions;
  /** Called with the next full options object on any control change. */
  onChange: (next: SpectrumDisplayOptions) => void;
  /** Hide the wavenumber-crop inputs (e.g. when zoom is driven elsewhere). */
  hideXRange?: boolean;
  /** Disable every control. */
  disabled?: boolean;
  className?: string;
}

const groupCls = "flex items-center gap-1.5 text-xs text-muted-foreground";
const selectCls =
  "border-input bg-background text-foreground focus-visible:ring-ring/50 focus-visible:border-ring h-8 cursor-pointer rounded-md border px-2 text-xs outline-none focus-visible:ring-[3px] disabled:pointer-events-none disabled:opacity-50";
const rangeCls =
  "accent-primary h-1 cursor-pointer disabled:pointer-events-none disabled:opacity-50";

/**
 * Compact, horizontally-flowing strip of plot-customisation controls, meant to
 * sit directly below a `SpectrumChart`. Fully controlled: it never holds state,
 * it just diffs `value` and calls `onChange` with the merged next object.
 *
 * Wraps onto multiple rows on narrow widths; never introduces an inner
 * scrollbar.
 */
export function PlotControls({
  value,
  onChange,
  hideXRange = false,
  disabled = false,
  className,
}: PlotControlsProps) {
  const v = { ...DEFAULT_DISPLAY_OPTIONS, ...value };
  const set = (patch: Partial<SpectrumDisplayOptions>) =>
    onChange({ ...value, ...patch });

  const parseNum = (raw: string): number | undefined => {
    if (raw.trim() === "") return undefined;
    const n = Number(raw);
    return Number.isFinite(n) ? n : undefined;
  };

  const offset = v.offset ?? 0;
  const lineWidth = v.lineWidth ?? 2;
  const cropCleared = value.xMin === undefined && value.xMax === undefined;

  return (
    <div
      className={cn(
        "border-border bg-card flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border px-3 py-2",
        className,
      )}
    >
      {/* Normalisation */}
      <label className={groupCls}>
        <span>Normalise</span>
        <select
          className={selectCls}
          disabled={disabled}
          value={v.normalize ?? "none"}
          onChange={(e) => set({ normalize: e.target.value as NormalizeMode })}
        >
          {NORMALIZE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      {/* Overlay vs stack */}
      <div className={groupCls} role="group" aria-label="Trace layout">
        <Segment
          active={!v.stacked}
          disabled={disabled}
          onClick={() => set({ stacked: false })}
        >
          Overlay
        </Segment>
        <Segment
          active={!!v.stacked}
          disabled={disabled}
          onClick={() => set({ stacked: true })}
        >
          Stack
        </Segment>
      </div>

      {/* Offset — only meaningful while stacked */}
      {v.stacked && (
        <label className={groupCls}>
          <span>Offset</span>
          <input
            type="range"
            min={0}
            max={2}
            step={0.05}
            value={offset}
            disabled={disabled}
            onChange={(e) => set({ offset: Number(e.target.value) })}
            className={cn(rangeCls, "w-24")}
            aria-label="Vertical offset between stacked traces"
          />
          <span className="w-8 text-right tabular-nums">
            {offset.toFixed(2)}
          </span>
        </label>
      )}

      {/* Legend / grid */}
      <div className={groupCls} role="group" aria-label="Chart guides">
        <Segment
          active={v.showLegend !== false}
          disabled={disabled}
          onClick={() => set({ showLegend: !(v.showLegend !== false) })}
        >
          Legend
        </Segment>
        <Segment
          active={v.showGrid !== false}
          disabled={disabled}
          onClick={() => set({ showGrid: !(v.showGrid !== false) })}
        >
          Grid
        </Segment>
      </div>

      {/* Line width */}
      <label className={groupCls}>
        <span>Line</span>
        <input
          type="range"
          min={0.5}
          max={4}
          step={0.25}
          value={lineWidth}
          disabled={disabled}
          onChange={(e) => set({ lineWidth: Number(e.target.value) })}
          className={cn(rangeCls, "w-20")}
          aria-label="Trace line width"
        />
        <span className="w-8 text-right tabular-nums">
          {lineWidth.toFixed(2)}
        </span>
      </label>

      {/* Wavenumber crop */}
      {!hideXRange && (
        <div className={groupCls}>
          <span>cm⁻¹</span>
          <Input
            type="number"
            inputMode="numeric"
            placeholder="min"
            disabled={disabled}
            value={value.xMin ?? ""}
            onChange={(e) => set({ xMin: parseNum(e.target.value) })}
            className="h-8 w-[4.5rem] px-2 text-xs"
            aria-label="Minimum wavenumber"
          />
          <span aria-hidden>–</span>
          <Input
            type="number"
            inputMode="numeric"
            placeholder="max"
            disabled={disabled}
            value={value.xMax ?? ""}
            onChange={(e) => set({ xMax: parseNum(e.target.value) })}
            className="h-8 w-[4.5rem] px-2 text-xs"
            aria-label="Maximum wavenumber"
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 px-2 text-xs"
            disabled={disabled || cropCleared}
            onClick={() => set({ xMin: undefined, xMax: undefined })}
          >
            Reset
          </Button>
        </div>
      )}
    </div>
  );
}

function Segment({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "h-8 rounded-md border px-2.5 text-xs font-medium transition-colors disabled:pointer-events-none disabled:opacity-50",
        active
          ? "border-primary bg-primary/10 text-primary"
          : "border-input bg-background text-muted-foreground hover:bg-accent hover:text-accent-foreground",
      )}
    >
      {children}
    </button>
  );
}
