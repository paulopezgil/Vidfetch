import type { FormEvent } from "react";
import Icon from "./Icon";
import IconButton from "./IconButton";

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit?: () => void;
  placeholder?: string;
  label: string;
  submitLabel?: string;
  submitIcon?: string;
  loading?: boolean;
  error?: boolean;
  describedBy?: string;
  className?: string;
}

/** Material 3 search bar with a trailing submit action. */
export default function SearchBar({
  value,
  onChange,
  onSubmit,
  placeholder,
  label,
  submitLabel = "Envia",
  submitIcon = "arrow_forward",
  loading = false,
  error = false,
  describedBy,
  className = "",
}: SearchBarProps) {
  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onSubmit?.();
  }

  return (
    <form
      onSubmit={handleSubmit}
      role="search"
      className={`flex h-14 items-center gap-2 rounded-full bg-surface-container-high pl-4 pr-1.5 focus-within:ring-2 focus-within:ring-primary ${className}`}
    >
      <Icon name="search" className="text-[24px] shrink-0 text-on-surface-variant" />
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={label}
        aria-invalid={error}
        aria-describedby={describedBy}
        className="h-full min-w-0 flex-1 bg-transparent text-body-large text-on-surface placeholder:text-on-surface-variant focus:outline-none"
      />
      <IconButton
        type="submit"
        variant="filled"
        label={submitLabel}
        disabled={loading}
      >
        <Icon
          name={loading ? "progress_activity" : submitIcon}
          className={`text-[24px] ${loading ? "animate-spin" : ""}`}
        />
      </IconButton>
    </form>
  );
}
