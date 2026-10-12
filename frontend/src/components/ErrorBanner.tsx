import Icon from "./Icon";

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
  id?: string;
}

/** Material 3 error container. */
export default function ErrorBanner({ message, onRetry, id }: ErrorBannerProps) {
  return (
    <div
      id={id}
      role="alert"
      className="flex items-start gap-3 rounded-md bg-error-container px-4 py-3 text-on-error-container"
    >
      <Icon name="error" className="text-[20px]" />
      <p className="min-w-0 flex-1 text-body-medium">{message}</p>
      {onRetry ? (
        <button
          onClick={onRetry}
          className="shrink-0 rounded-sm px-2 py-1 text-label-large transition-colors hover:bg-on-error-container/8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-on-error-container"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}
