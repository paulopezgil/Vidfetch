import type { InputHTMLAttributes, ReactNode } from "react";

interface TextFieldProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "placeholder"> {
  /** Persistent, always-visible label (never a placeholder-only label). */
  label: string;
  helperText?: string;
  /** Marks the field invalid and tints the label, underline and helper text. */
  error?: boolean;
  /** Optional trailing control, e.g. a password visibility toggle. */
  endAdornment?: ReactNode;
}

/**
 * Material 3 filled text field.
 *
 * The floating label collapses into the top padding on focus or when the
 * field has a value; the active indicator thickens to 2px in `primary`.
 */
export default function TextField({
  id,
  label,
  helperText,
  error = false,
  endAdornment,
  className = "",
  type = "text",
  ...rest
}: TextFieldProps) {
  const helperId = helperText ? `${id}-helper` : undefined;

  return (
    <div className={className}>
      <div className="group relative flex min-h-14 items-center rounded-t-xs bg-surface-container-highest focus-within:ring-2 focus-within:ring-secondary">
        <input
          id={id}
          type={type}
          placeholder=" "
          aria-invalid={error || undefined}
          aria-describedby={helperId}
          className={`peer min-h-14 w-full bg-transparent px-4 pb-1 pt-5 text-body-large text-on-surface outline-none placeholder:text-transparent disabled:pointer-events-none disabled:opacity-[0.38] ${
            endAdornment ? "pr-14" : ""
          }`}
          {...rest}
        />
        <label
          htmlFor={id}
          className={`pointer-events-none absolute left-4 top-1.5 text-body-small transition-all duration-150 peer-placeholder-shown:top-4 peer-placeholder-shown:text-body-large peer-focus:top-1.5 peer-focus:text-body-small ${
            error ? "text-error" : "text-on-surface-variant"
          }`}
        >
          {label}
        </label>
        {endAdornment ? (
          <div className="absolute right-1.5 top-1/2 -translate-y-1/2">
            {endAdornment}
          </div>
        ) : null}
        <span
          aria-hidden="true"
          className={`pointer-events-none absolute inset-x-0 bottom-0 h-px transition-[background-color,height] ${
            error
              ? "h-0.5 bg-error"
              : "bg-outline group-focus-within:h-0.5 group-focus-within:bg-primary"
          }`}
        />
      </div>
      {helperText ? (
        <p
          id={helperId}
          className={`mt-1 px-4 text-body-small ${
            error ? "text-error" : "text-on-surface-variant"
          }`}
        >
          {helperText}
        </p>
      ) : null}
    </div>
  );
}
