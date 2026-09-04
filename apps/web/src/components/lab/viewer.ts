/**
 * Shared sizing for the Data Lab's spectrum viewer.
 *
 * The viewer is the reason the Lab exists, so it owns roughly two thirds of the
 * viewport height — floored so it stays usable on a short laptop screen, and
 * capped so it doesn't become a letterbox on a large monitor.
 *
 * Every state of the viewer (the chart, its loading skeleton, and the "nothing
 * selected" placeholder) must use this same class, or the panel jumps height as
 * a spectrum loads.
 */
export const VIEWER_HEIGHT = "h-[clamp(320px,calc(100vh-19rem),720px)]";
