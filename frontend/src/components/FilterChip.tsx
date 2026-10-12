import Icon from "./Icon";

interface FilterChipProps {
  label: string;
  selected: boolean;
  onClick: () => void;
}

/** Material 3 filter chip (single-select). */
export default function FilterChip({ label, selected, onClick }: FilterChipProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-sm border px-3 text-label-large transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary ${
        selected
          ? "border-transparent bg-primary text-on-primary"
          : "border-outline text-on-surface-variant hover:bg-on-surface/8 active:bg-on-surface/12"
      }`}
    >
      {selected ? <Icon name="check" className="text-[18px]" /> : null}
      {label}
    </button>
  );
}
