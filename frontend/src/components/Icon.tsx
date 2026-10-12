interface IconProps {
  /** Material Symbols ligature name, e.g. "download". */
  name: string;
  /** Tailwind text-size utility sets the glyph size (default 24px). */
  className?: string;
  filled?: boolean;
}

/** Renders a Material Symbols Rounded glyph. */
export default function Icon({ name, className = "", filled = false }: IconProps) {
  return (
    <span
      aria-hidden="true"
      className={`material-symbols-rounded ${filled ? "filled" : ""} ${className}`}
    >
      {name}
    </span>
  );
}
