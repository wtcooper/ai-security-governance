/**
 * The threshold rule — this app's one signature element.
 *
 * Every number in a governance run exists to be compared against a written bar, and the
 * comparison is the product. So instead of a score badge, each gate gets a hairline measure
 * with a tick at the threshold and a dot at the measured value. It shows, in one glance and
 * almost no ink: where the value sits, where the bar is, which side of it counts as good, and
 * how much room there is.
 *
 * Deliberately not a chart. No axes, no gridlines, no gradient, no animation. A gauge would
 * imply a precision these placeholder thresholds do not have.
 *
 * The shaded span is the *acceptable* region, so "inside the shading" always means passing
 * regardless of which direction the metric runs.
 */

type Props = {
  value: number | null;
  threshold: number;
  /** "higher_is_better" | "lower_is_better" — decides which side of the tick is acceptable. */
  direction: string;
  passed: boolean;
};

export function ThresholdRule({ value, threshold, direction, passed }: Props) {
  const higherIsBetter = direction === "higher_is_better";
  // Metrics are stored as 0-1 rates, so the track maps directly onto the unit interval.
  const clamp = (n: number) => Math.min(Math.max(n, 0), 1);
  const tick = clamp(threshold) * 100;

  const acceptable = higherIsBetter
    ? { left: tick, width: 100 - tick }
    : { left: 0, width: tick };

  const tone = passed ? "var(--color-pass)" : "var(--color-block)";

  if (value === null) {
    return (
      <div className="flex items-center gap-2">
        <div className="relative h-[3px] w-28 bg-rule" aria-hidden="true">
          <span className="absolute top-[-3px] h-[9px] w-px bg-rule-strong" style={{ left: `${tick}%` }} />
        </div>
        <span className="text-[11px] text-faint">not measured</span>
      </div>
    );
  }

  const position = clamp(value) * 100;

  return (
    <div
      className="flex items-center gap-2"
      role="img"
      aria-label={
        `measured ${value.toPrecision(3)}, threshold ${higherIsBetter ? "at least" : "at most"} ` +
        `${threshold}, ${passed ? "passing" : "failing"}`
      }
    >
      <div className="relative h-[3px] w-28 bg-rule">
        {/* Acceptable region. Faint on purpose — it is context, not the reading. */}
        <span
          className="absolute inset-y-0 bg-rule-strong/60"
          style={{ left: `${acceptable.left}%`, width: `${acceptable.width}%` }}
        />
        {/* The bar itself. */}
        <span
          className="absolute top-[-4px] h-[11px] w-px bg-ink"
          style={{ left: `${tick}%` }}
        />
        {/* The measurement. */}
        <span
          className="absolute top-1/2 h-[9px] w-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface"
          style={{ left: `${position}%`, backgroundColor: tone }}
        />
      </div>
      <span className="tnum text-[11px] text-faint">
        {higherIsBetter ? "≥" : "≤"} {threshold}
      </span>
    </div>
  );
}
