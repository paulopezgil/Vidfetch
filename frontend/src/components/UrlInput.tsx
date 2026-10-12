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
      setLocalError("Introdueix una URL de vídeo o de llista de reproducció.");
      return;
    }
    if (!isValidUrl(url)) {
      setLocalError("Introdueix una URL http(s) vàlida.");
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
        label="URL de vídeo o de llista de reproducció"
        placeholder="Enganxa una URL de vídeo o de llista de reproducció de YouTube"
        submitLabel="Obtén la informació"
      />
      {shownError ? <ErrorBanner id="url-error" message={shownError} /> : null}
    </div>
  );
}
