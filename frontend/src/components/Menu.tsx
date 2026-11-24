import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import Icon from "./Icon";

export interface MenuAction {
  /** Stable key for the action. */
  id: string;
  label: string;
  /** Material Symbols ligature, shown before the label. */
  icon?: string;
  onSelect: () => void;
}

interface MenuProps {
  /** Accessible name of the icon-button trigger. */
  label: string;
  actions: MenuAction[];
  disabled?: boolean;
}

/**
 * Material 3 overflow menu.
 *
 * The trigger is an icon button with `aria-haspopup="menu"`; the popup uses
 * `role="menu"`/`role="menuitem"` with roving focus (arrow keys, Home, End).
 * Escape and outside pointer presses close it and return focus to the trigger.
 */
export default function Menu({ label, actions, disabled }: MenuProps) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const close = useCallback((restoreFocus = true) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;

    const frame = window.requestAnimationFrame(() => {
      itemRefs.current[0]?.focus();
    });

    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (menuRef.current?.contains(target)) return;
      if (triggerRef.current?.contains(target)) return;
      setOpen(false);
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      }
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (actions.length === 0) return null;

  function focusItem(index: number) {
    const count = itemRefs.current.length;
    if (count === 0) return;
    const next = (index + count) % count;
    itemRefs.current[next]?.focus();
  }

  function onMenuKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const active = itemRefs.current.findIndex(
      (item) => item === document.activeElement,
    );
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focusItem(active + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        focusItem(active - 1);
        break;
      case "Home":
        event.preventDefault();
        focusItem(0);
        break;
      case "End":
        event.preventDefault();
        focusItem(itemRefs.current.length - 1);
        break;
      case "Tab":
        // Let focus leave the menu, then hide it.
        setOpen(false);
        break;
      default:
        break;
    }
  }

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={label}
        title={label}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
          }
        }}
        className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-on-surface-variant transition-colors duration-200 hover:bg-on-surface/8 active:bg-on-surface/12 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary focus-visible:ring-offset-2 focus-visible:ring-offset-surface disabled:pointer-events-none disabled:opacity-[0.38]"
      >
        <Icon name="more_vert" className="text-[20px]" />
      </button>

      {open ? (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label={label}
          aria-orientation="vertical"
          onKeyDown={onMenuKeyDown}
          className="absolute right-0 top-full z-30 mt-1 min-w-[12rem] overflow-hidden rounded-xs bg-surface-container py-2 shadow-elevation-2"
        >
          {actions.map((action, index) => (
            <button
              key={action.id}
              ref={(element) => {
                itemRefs.current[index] = element;
              }}
              type="button"
              role="menuitem"
              tabIndex={-1}
              onClick={() => {
                close(true);
                action.onSelect();
              }}
              className="flex h-12 w-full items-center gap-3 px-3 text-left text-label-large text-on-surface transition-colors hover:bg-on-surface/8 focus-visible:bg-on-surface/12 focus-visible:outline-none active:bg-on-surface/12"
            >
              {action.icon ? (
                <Icon name={action.icon} className="text-[20px]" />
              ) : null}
              <span className="min-w-0 flex-1 truncate">{action.label}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
