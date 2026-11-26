/**
 * Animated bars marking the row that is currently playing.
 *
 * The three bars animate only when motion is allowed; the CSS in `index.css`
 * swaps them for a static, differently-sized set when the user prefers
 * reduced motion. The label is exposed to assistive technology, while the bars
 * themselves are decorative.
 */
export default function NowPlayingIndicator({
  className = "",
}: {
  className?: string;
}) {
  return (
    <span
      role="img"
      aria-label="S’està reproduint"
      title="S’està reproduint"
      className={`now-playing-indicator shrink-0 ${className}`}
    >
      <span aria-hidden="true" className="now-playing-bar" />
      <span aria-hidden="true" className="now-playing-bar" />
      <span aria-hidden="true" className="now-playing-bar" />
    </span>
  );
}
