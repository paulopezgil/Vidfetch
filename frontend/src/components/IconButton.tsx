import type { ReactNode } from "react";

type Variant = "default" | "danger";

interface IconButtonProps {
  /** Accessible name; also shown as the tooltip. */
  label: string;
  variant?: Variant;
  className?: string;
  children: ReactNode;
  /** Render as a link when an href is provided. */
  href?: string;
  type?: "button" | "submit";
  disabled?: boolean;
  onClick?: () => void;
}

const variants: Record<Variant, string> = {
  default: "text-fg-secondary hover:bg-surface-2 hover:text-fg",
  danger: "text-fg-secondary hover:bg-danger/15 hover:text-danger",
};

/**
 * Square, icon-only control with a 40px target (Material Web icon-button
 * size), a visible focus ring, and a required accessible name.
 */
export default function IconButton({
  label,
  variant = "default",
  className = "",
  children,
  href,
  type = "button",
  disabled,
  onClick,
}: IconButtonProps) {
  const classes = `inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/70 disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`;

  if (href) {
    return (
      <a href={href} className={classes} title={label} aria-label={label}>
        {children}
      </a>
    );
  }

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={classes}
      title={label}
      aria-label={label}
    >
      {children}
    </button>
  );
}
