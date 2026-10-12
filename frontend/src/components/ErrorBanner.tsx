import { AlertCircle } from "lucide-react";

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
  id?: string;
}

export default function ErrorBanner({ message, onRetry, id }: ErrorBannerProps) {
  return (
    <div
      id={id}
      role="alert"
      className="flex items-start gap-3 rounded-lg border border-danger/30 bg-danger/10 px-4 py-3"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-danger">{message}</p>
      </div>
      {onRetry ? (
        <button
          onClick={onRetry}
          className="shrink-0 text-xs font-medium text-danger underline underline-offset-2 hover:text-danger/80"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}
