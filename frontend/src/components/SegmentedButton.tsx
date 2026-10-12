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
}

/** Material 3 single-select segmented button. */
export default function SegmentedButton({
  options,
  value,
  onChange,
  label,
  className = "",
}: SegmentedButtonProps) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={`inline-flex h-10 items-stretch overflow-hidden rounded-full border border-outline ${className}`}
    >
      {options.map((option, index) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={option.disabled}
            onClick={() => onChange(option.value)}
            className={`inline-flex items-center gap-2 px-4 text-label-large transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-secondary disabled:pointer-events-none disabled:opacity-[0.38] ${
              index > 0 ? "border-l border-outline" : ""
            } ${
              selected
                ? "bg-secondary-container text-on-secondary-container"
                : "text-on-surface hover:bg-on-surface/8"
            }`}
          >
            {selected ? (
              <Icon name="check" className="text-[18px]" />
            ) : option.icon ? (
              <Icon name={option.icon} className="text-[18px]" />
            ) : null}
            <span className="whitespace-nowrap">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
