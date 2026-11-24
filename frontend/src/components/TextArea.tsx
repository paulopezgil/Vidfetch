import type { TextareaHTMLAttributes } from "react";

interface TextAreaProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "placeholder"> {
  /** Persistent, always-visible label (never a placeholder-only label). */
  label: string;
  helperText?: string;
  /** Marks the field invalid and tints the label, underline and helper text. */
  error?: boolean;
}

/**
 * Material 3 filled multi-line text field.
 *
 * Mirrors `TextField` (floating label, 2 px `primary` active indicator) and
 * lets the user resize vertically so long descriptions stay readable.
 */
export default function TextArea({
  id,
  label,
  helperText,
  error = false,
  rows = 3,
  className = "",
  ...rest
}: TextAreaProps) {
  const helperId = helperText ? `${id}-helper` : undefined;

  return (
    <div className={className}>
      <div className="group relative flex rounded-t-xs bg-surface-container-highest focus-within:ring-2 focus-within:ring-secondary">
        <textarea
          id={id}
          rows={rows}
          placeholder=" "
          aria-invalid={error || undefined}
          aria-describedby={helperId}
          className="peer min-h-20 w-full resize-y bg-transparent px-4 pb-2 pt-6 text-body-large text-on-surface outline-none placeholder:text-transparent disabled:pointer-events-none disabled:opacity-[0.38]"
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
