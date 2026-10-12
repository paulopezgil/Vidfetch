import { useState, type FormEvent } from "react";
import { Link2 } from "lucide-react";
import Button from "./Button";
import Spinner from "./Spinner";
import ErrorBanner from "./ErrorBanner";

interface UrlInputProps {
  onFetch: (url: string) => void;
  loading: boolean;
  error: string | null;
}

function isValidUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export default function UrlInput({ onFetch, loading, error }: UrlInputProps) {
  const [value, setValue] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    const url = value.trim();
    if (!url) {
      setLocalError("Enter a video or playlist URL.");
      return;
    }
    if (!isValidUrl(url)) {
      setLocalError("Enter a valid http(s) URL.");
      return;
    }
    setLocalError(null);
    onFetch(url);
  }

  return (
    <div className="space-y-3">
      <form
        onSubmit={submit}
        className="flex flex-col gap-2 sm:flex-row"
        noValidate
      >
        <div className="relative flex-1">
          <Link2 className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted" />
          <input
            type="text"
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              if (localError) setLocalError(null);
            }}
            placeholder="Paste a YouTube video or playlist URL"
            aria-label="Video or playlist URL"
            className="h-11 w-full rounded-lg border border-line bg-surface-1 pl-10 pr-3 text-sm text-fg placeholder:text-fg-muted focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/50"
          />
        </div>
        <Button type="submit" disabled={loading} className="h-11 shrink-0">
          {loading ? (
            <>
              <Spinner /> Fetching…
            </>
          ) : (
            "Fetch Info"
          )}
        </Button>
      </form>
      {localError ? <ErrorBanner message={localError} /> : null}
      {error && !localError ? <ErrorBanner message={error} /> : null}
    </div>
  );
}
