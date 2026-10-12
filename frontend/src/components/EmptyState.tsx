import type { ReactNode } from "react";

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export default function EmptyState({
  icon,
  title,
  description,
  action,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-2 text-fg-muted">
        {icon}
      </div>
      <div>
        <p className="text-base font-semibold text-fg">{title}</p>
        {description ? (
          <p className="mt-1 max-w-sm text-sm text-fg-secondary">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}
