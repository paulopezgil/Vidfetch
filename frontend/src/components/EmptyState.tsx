import type { ReactNode } from "react";
import Icon from "./Icon";

interface EmptyStateProps {
  /** Material Symbols name. */
  icon: string;
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
    <div className="flex flex-col items-center justify-center gap-4 px-6 py-16 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-container-high text-on-surface-variant">
        <Icon name={icon} className="text-[32px]" />
      </div>
      <div>
        <h3 className="text-title-medium text-on-surface">{title}</h3>
        {description ? (
          <p className="mx-auto mt-1 max-w-sm text-body-medium text-on-surface-variant">
            {description}
          </p>
        ) : null}
      </div>
      {action}
    </div>
  );
}
