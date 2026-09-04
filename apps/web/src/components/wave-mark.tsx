/**
 * The spectrum waveform mark used in the logo lockup, shared by the app nav and
 * the marketing header so the two brands cannot drift apart.
 */
export function WaveMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 14 14" fill="none" className={className} aria-hidden>
      <polyline
        points="0,10 2,10 3,7 4,9 5,5 6,8 7,4 8,6 9,8 10,4 11,7 12,6 14,10"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
