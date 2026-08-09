/**
 * A term of art with its definition one hover (or keyboard focus) away.
 *
 * Pure CSS, no client JS: the tooltip is a positioned child revealed on hover/focus-within,
 * so it works in server components and costs nothing. Used for the handful of words this
 * app cannot avoid — provenance, composite, unresolved — so a first-time reviewer never has
 * to leave the page to decode a label.
 */
export function Term({ label, tip }: { label: string; tip: string }) {
  return (
    <span className="term" tabIndex={0}>
      {label}
      <span role="tooltip" className="term-tip">
        {tip}
      </span>
    </span>
  );
}
