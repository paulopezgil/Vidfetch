interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  disabled?: boolean;
}

/** Material 3 switch for immediate binary settings. */
export default function Switch({
  checked,
  onChange,
  label,
  disabled,
}: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="group inline-flex items-center gap-3 rounded-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary focus-visible:ring-offset-2 focus-visible:ring-offset-surface disabled:pointer-events-none disabled:opacity-[0.38]"
    >
      <span
        className={`relative inline-flex h-8 w-[52px] shrink-0 items-center rounded-full transition-colors duration-200 ${
          checked
            ? "bg-primary"
            : "border-2 border-outline bg-surface-container-highest"
        }`}
      >
        <span
          className={`absolute rounded-full transition-all duration-200 ${
            checked
              ? "left-[26px] h-6 w-6 bg-on-primary"
              : "left-[6px] h-4 w-4 bg-outline"
          }`}
        />
      </span>
      {label ? (
        <span className="text-label-large text-on-surface">{label}</span>
      ) : null}
    </button>
  );
}
