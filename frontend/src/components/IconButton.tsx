import type { ReactNode } from "react";

type Variant = "standard" | "filled" | "tonal" | "outlined" | "danger";
type Size = "sm" | "md";

interface IconButtonProps {
  /** Required accessible name; also used as the tooltip by default. */
  label: string;
  /** Longer tooltip text when it should differ from the accessible name. */
  title?: string;
  variant?: Variant;
  size?: Size;
  className?: string;
  children: ReactNode;
  /** Render as a link when an href is provided. */
  href?: string;
  type?: "button" | "submit";
  disabled?: boolean;
  /** Toggle state for controls such as the offline-save button. */
  ariaPressed?: boolean;
  /** Expansion state for controls that disclose a panel. */
  ariaExpanded?: boolean;
  /** Id of the panel a disclosure control expands. */
  ariaControls?: string;
  onClick?: () => void;
}

/** Material 3 icon buttons (circular, 40 or 48 px). */
const variants: Record<Variant, string> = {
  standard:
    "text-on-surface-variant hover:bg-on-surface/8 active:bg-on-surface/12",
  filled: "bg-primary text-on-primary hover:shadow-elevation-1 active:shadow-none",
  tonal:
    "bg-secondary-container text-on-secondary-container hover:bg-secondary-container/90",
  outlined:
    "border border-outline text-on-surface-variant hover:bg-on-surface/8",
  danger:
    "text-on-surface-variant hover:bg-error/8 hover:text-error active:bg-error/12",
};

const sizes: Record<Size, string> = {
  sm: "h-10 w-10",
  md: "h-12 w-12",
};

export default function IconButton({
  label,
  title,
  variant = "standard",
  size = "sm",
  className = "",
  children,
  href,
  type = "button",
  disabled,
  ariaPressed,
  ariaExpanded,
  ariaControls,
  onClick,
}: IconButtonProps) {
  const classes = `inline-flex shrink-0 items-center justify-center rounded-full transition-[background-color,color,box-shadow] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary focus-visible:ring-offset-2 focus-visible:ring-offset-surface disabled:pointer-events-none disabled:opacity-[0.38] ${variants[variant]} ${sizes[size]} ${className}`;

  if (href) {
    return (
      <a href={href} className={classes} title={title ?? label} aria-label={label}>
        {children}
      </a>
    );
  }

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      aria-pressed={ariaPressed}
      aria-expanded={ariaExpanded}
      aria-controls={ariaControls}
      className={classes}
      title={title ?? label}
      aria-label={label}
    >
      {children}
    </button>
  );
}
