import type { HTMLAttributes, ReactNode } from "react";

type Variant = "elevated" | "filled" | "outlined";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: Variant;
  children: ReactNode;
}

/** Material 3 card. */
const variants: Record<Variant, string> = {
  elevated: "bg-surface-container-low shadow-elevation-1",
  filled: "bg-surface-container-highest",
  outlined: "bg-surface border border-outline-variant",
};

export default function Card({
  variant = "filled",
  className = "",
  children,
  ...rest
}: CardProps) {
  return (
    <div className={`rounded-md ${variants[variant]} ${className}`} {...rest}>
      {children}
    </div>
  );
}
