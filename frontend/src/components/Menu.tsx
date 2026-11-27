import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import Icon from "./Icon";

export interface MenuAction {
  /** Stable key for the action. */
  id: string;
  label: string;
  /** Material Symbols ligature, shown before the label. */
  icon?: string;
  /** Checkmark state for radio-style menus such as sorting. */
  selected?: boolean;
  /** Destructive actions use the error role for text and hover states. */
  danger?: boolean;
  onSelect: () => void;
}

interface MenuProps {
  /** Accessible name of the trigger and the popup. */
  label: string;
  /** Material Symbols ligature for the trigger; defaults to the overflow icon. */
  icon?: string;
  actions: MenuAction[];
  disabled?: boolean;
  /**
   * Custom trigger content, e.g. a labelled quality pill. When omitted the
   * trigger stays the default overflow icon button.
   */
  trigger?: ReactNode;
  /** Classes for the trigger button; defaults to the icon-button styles. */
  triggerClassName?: string;
}

interface MenuPosition {
  top: number;
  left: number;
}

/** Viewport margin kept between the popup and every window edge. */
const EDGE = 8;
/** Gap between the trigger and the popup. */
const GAP = 4;
/** Width assumed until the popup has been measured. */
const FALLBACK_WIDTH = 192;

/**
 * Material 3 overflow menu.
 *
 * The trigger defaults to an icon button and can be replaced with labelled
 * content via `trigger`; both carry `aria-haspopup="menu"`. The popup renders
 * through a portal on `document.body` with fixed positioning anchored to the
 * trigger's bounding box. That keeps it above the surrounding list and stops a
 * card's `overflow-hidden` from clipping it — an in-flow popup used to push the
 * row and scroll the list when it received focus.
 *
 * The popup is right-aligned with the trigger, flips above when there is no
 * room below, clamps to the viewport and re-anchors on resize/scroll. Focus
 * moves into the menu with `preventScroll`, so opening it never moves the page.
 * `role="menu"`/`role="menuitem"` with roving focus (arrow keys, Home, End);
 * Escape and outside pointer presses close it and return focus to the trigger.
 */
export default function Menu({
  label,
  icon = "more_vert",
  actions,
  disabled,
  trigger,
  triggerClassName,
}: MenuProps) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<MenuPosition | null>(null);
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const close = useCallback((restoreFocus = true) => {
    setOpen(false);
    setPosition(null);
    if (restoreFocus) triggerRef.current?.focus({ preventScroll: true });
  }, []);

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const menu = menuRef.current;
    const width = menu?.offsetWidth || FALLBACK_WIDTH;
    const height = menu?.offsetHeight ?? 0;

    // Right-aligned with the trigger, then clamped inside the viewport.
    let left = rect.right - width;
    left = Math.min(
      Math.max(EDGE, left),
      Math.max(EDGE, window.innerWidth - width - EDGE),
    );

    // Prefer below the trigger; flip above when the popup would overflow.
    let top = rect.bottom + GAP;
    if (height > 0 && top + height > window.innerHeight - EDGE) {
      const above = rect.top - GAP - height;
      if (above >= EDGE) top = above;
    }
    top = Math.min(
      Math.max(EDGE, top),
      Math.max(EDGE, window.innerHeight - height - EDGE),
    );

    setPosition((current) =>
      current && current.top === top && current.left === left
        ? current
        : { top, left },
    );
  }, []);

  // Measure right after the popup mounts, before the browser paints it.
  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
  }, [open, updatePosition]);

  useEffect(() => {
    if (!open) return;

    const frame = window.requestAnimationFrame(() => {
      // `preventScroll` is the key detail: focusing the first item must not
      // scroll a list row into view and shove the whole page.
      itemRefs.current[0]?.focus({ preventScroll: true });
      updatePosition();
    });

    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (menuRef.current?.contains(target)) return;
      if (triggerRef.current?.contains(target)) return;
      setOpen(false);
      setPosition(null);
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        setPosition(null);
        triggerRef.current?.focus({ preventScroll: true });
      }
    }

    function onViewportChange() {
      updatePosition();
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onViewportChange);
    // Capture scroll from any scroll container, not just the document.
    window.addEventListener("scroll", onViewportChange, true);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [open, updatePosition]);

  if (actions.length === 0) return null;

  function focusItem(index: number) {
    const count = itemRefs.current.length;
    if (count === 0) return;
    const next = (index + count) % count;
    itemRefs.current[next]?.focus({ preventScroll: true });
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
        setPosition(null);
        break;
      default:
        break;
    }
  }

  const style: CSSProperties = {
    position: "fixed",
    top: position?.top ?? 0,
    left: position?.left ?? 0,
    visibility: position ? "visible" : "hidden",
  };

  return (
    <>
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
        className={
          triggerClassName ??
          "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-on-surface-variant transition-colors duration-200 hover:bg-on-surface/8 active:bg-on-surface/12 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary focus-visible:ring-offset-2 focus-visible:ring-offset-surface disabled:pointer-events-none disabled:opacity-[0.38]"
        }
      >
        {trigger ?? <Icon name={icon} className="text-[20px]" />}
      </button>

      {open
        ? createPortal(
            <div
              ref={menuRef}
              id={menuId}
              role="menu"
              aria-label={label}
              aria-orientation="vertical"
              onKeyDown={onMenuKeyDown}
              style={style}
              className="z-[90] max-h-[min(70vh,calc(100vh-1rem))] min-w-[12rem] max-w-[calc(100vw-1rem)] overflow-y-auto rounded-xs bg-surface-container py-2 shadow-elevation-3"
            >
              {actions.map((action, index) => (
                <button
                  key={action.id}
                  ref={(element) => {
                    itemRefs.current[index] = element;
                  }}
                  type="button"
                  role={
                    action.selected === undefined ? "menuitem" : "menuitemradio"
                  }
                  aria-checked={action.selected}
                  tabIndex={-1}
                  onClick={() => {
                    close(true);
                    action.onSelect();
                  }}
                  className={`flex h-12 w-full items-center gap-3 px-3 text-left text-label-large transition-colors focus-visible:outline-none ${
                    action.danger
                      ? "text-error hover:bg-error/8 focus-visible:bg-error/12 active:bg-error/12"
                      : "text-on-surface hover:bg-on-surface/8 focus-visible:bg-on-surface/12 active:bg-on-surface/12"
                  }`}
                >
                  {action.icon ? (
                    <Icon name={action.icon} className="text-[20px]" />
                  ) : null}
                  <span className="min-w-0 flex-1 truncate">
                    {action.label}
                  </span>
                  {action.selected ? (
                    <Icon name="check" className="text-[20px] text-primary" />
                  ) : null}
                </button>
              ))}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
