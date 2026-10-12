import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import Icon from "./Icon";

type ToastType = "success" | "error" | "info";

interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

type Push = (message: string, type?: ToastType) => void;

const ToastContext = createContext<Push>(() => {});

export function useToast(): Push {
  return useContext(ToastContext);
}

const icons: Record<ToastType, string> = {
  success: "check_circle",
  error: "error",
  info: "info",
};

/** Material 3 snackbar host. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback<Push>((message, type = "info") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4500);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col items-center gap-2 sm:inset-x-0"
        role="region"
        aria-label="Notificacions"
        aria-live="polite"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className="pointer-events-auto flex w-full max-w-lg items-center gap-3 rounded-xs bg-inverse-surface px-4 py-3 text-body-medium text-inverse-on-surface shadow-elevation-3"
          >
            <Icon name={icons[t.type]} className="text-[20px] shrink-0" />
            <span className="min-w-0 flex-1">{t.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
