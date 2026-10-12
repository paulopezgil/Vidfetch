import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "filled" | "tonal" | "outlined" | "text" | "elevated" | "danger";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
}

/** Material 3 common buttons. */
const variants: Record<Variant, string> = {
  filled:
    "bg-primary text-on-primary hover:shadow-elevation-1 active:shadow-none",
  tonal:
    "bg-secondary-container text-on-secondary-container hover:bg-secondary-container/90 active:bg-secondary-container/80",
  outlined:
    "border border-outline text-primary hover:bg-primary/8 active:bg-primary/12",
  text: "text-primary hover:bg-primary/8 active:bg-primary/12",
  elevated:
    "bg-surface-container-low text-primary shadow-elevation-1 hover:shadow-elevation-2",
  danger:
    "bg-error text-on-error hover:shadow-elevation-1 active:shadow-none",
};

const sizes: Record<Size, string> = {
  sm: "h-9 px-4 text-label-large",
  md: "h-10 px-6 text-label-large",
};

export default function Button({
  variant = "filled",
  size = "md",
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium transition-[background-color,box-shadow] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary focus-visible:ring-offset-2 focus-visible:ring-offset-surface disabled:pointer-events-none disabled:opacity-[0.38] ${variants[variant]} ${sizes[size]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
