import Icon from "./Icon";

interface Option {
  value: string;
  label: string;
  icon?: string;
  disabled?: boolean;
}

interface SegmentedButtonProps {
  options: Option[];
  value: string;
  onChange: (value: string) => void;
  label?: string;
  className?: string;
  /**
   * Icon-only below `sm`, with the label still exposed as the accessible name.
   * Keeps a long section switch on one line next to a trailing action.
   */
  compact?: boolean;
}

/** Material 3 single-select segmented button. */
export default function SegmentedButton({
  options,
  value,
  onChange,
  label,
  className = "",
  compact = false,
}: SegmentedButtonProps) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={`flex h-10 w-full items-stretch overflow-hidden rounded-full border border-outline sm:inline-flex sm:w-auto ${className}`}
    >
      {options.map((option, index) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={compact ? option.label : undefined}
            title={compact ? option.label : undefined}
            disabled={option.disabled}
            onClick={() => onChange(option.value)}
            className={`inline-flex min-w-0 flex-1 items-center justify-center gap-1.5 px-2.5 text-label-large transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-secondary disabled:pointer-events-none disabled:opacity-[0.38] sm:flex-none sm:gap-2 sm:px-4 ${
              index > 0 ? "border-l border-outline" : ""
            } ${
              selected
                ? "bg-primary text-on-primary"
                : "text-on-surface hover:bg-on-surface/8"
            }`}
          >
            {compact ? (
              option.icon ? (
                <Icon name={option.icon} className="text-[18px]" />
              ) : null
            ) : selected ? (
              <Icon name="check" className="text-[18px]" />
            ) : option.icon ? (
              <Icon
                name={option.icon}
                className="hidden text-[18px] sm:inline"
              />
            ) : null}
            <span
              className={
                compact
                  ? "sr-only whitespace-nowrap sm:not-sr-only"
                  : "whitespace-nowrap"
              }
            >
              {option.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
