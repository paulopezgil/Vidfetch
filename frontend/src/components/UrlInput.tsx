import { useState } from "react";
import ErrorBanner from "./ErrorBanner";
import SearchBar from "./SearchBar";

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

  function submit() {
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

  const shownError = localError ?? error;

  return (
    <div className="space-y-3">
      <SearchBar
        value={value}
        onChange={(next) => {
          setValue(next);
          if (localError) setLocalError(null);
        }}
        onSubmit={submit}
        loading={loading}
        error={Boolean(shownError)}
        describedBy={shownError ? "url-error" : undefined}
        label="Video or playlist URL"
        placeholder="Paste a YouTube video or playlist URL"
        submitLabel="Fetch info"
      />
      {shownError ? <ErrorBanner id="url-error" message={shownError} /> : null}
    </div>
  );
}
