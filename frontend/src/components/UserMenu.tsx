import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import Icon from "./Icon";

/** Read a non-empty string out of the Supabase `user_metadata` bag. */
function readMetadataString(metadata: unknown, key: string): string | null {
  if (typeof metadata !== "object" || metadata === null) return null;
  const value = (metadata as Record<string, unknown>)[key];
  return typeof value === "string" && value.trim() !== "" ? value.trim() : null;
}

/** Provider avatar URL, preferring the Google `avatar_url` claim. */
function avatarUrlFor(metadata: unknown): string | null {
  return (
    readMetadataString(metadata, "avatar_url") ??
    readMetadataString(metadata, "picture")
  );
}

/**
 * Text fallback for the avatar.
 *
 * A name-like `full_name`/`name` yields two initials (first + last word);
 * everything else falls back to the first letter of the account email.
 */
function initialsFor(email: string, metadata: unknown): string | null {
  const fullName =
    readMetadataString(metadata, "full_name") ??
    readMetadataString(metadata, "name");
  if (fullName) {
    const words = fullName.split(/\s+/).filter(Boolean);
    if (words.length >= 2) {
      const first = words[0].charAt(0);
      const last = words[words.length - 1].charAt(0);
      return `${first}${last}`.toLocaleUpperCase();
    }
  }
  const source = email.trim() || fullName || "";
  const first = source.charAt(0);
  return first ? first.toLocaleUpperCase() : null;
}

interface MenuItem {
  id: string;
  label: string;
  icon: string;
  onSelect: () => void;
}

/**
 * Material 3 account menu for the top app bar.
 *
 * The trigger is a 40 px avatar button with `aria-haspopup="menu"`; the popup
 * uses `role="menu"`/`role="menuitem"` with roving focus (arrow keys, Home,
 * End). Escape and outside pointer presses close it and return focus to the
 * avatar. It renders nothing without a profile, so it cannot flash during the
 * auth bootstrap.
 */
export default function UserMenu() {
  const { session, profile, signOut } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const metadata = session?.user.user_metadata;
  const avatarUrl = avatarUrlFor(metadata);

  useEffect(() => {
    // A different account (or a refreshed claim) deserves a fresh attempt.
    setImageFailed(false);
  }, [avatarUrl]);

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

  if (!profile) return null;

  const label = `Compte de ${profile.email}`;
  const roleLabel = profile.app_role === "admin" ? "Administració" : "Usuari";
  const shownAvatarUrl = imageFailed ? null : avatarUrl;
  const initials = shownAvatarUrl ? null : initialsFor(profile.email, metadata);

  async function leaveSession() {
    setBusy(true);
    try {
      // `signOut` also clears the identity-scoped offline data, so the next
      // account cannot see this library or replay these edits.
      await signOut();
    } finally {
      navigate("/login", { replace: true });
    }
  }

  const items: MenuItem[] = [
    {
      id: "switch-account",
      label: "Canvia de compte",
      icon: "swap_horiz",
      onSelect: () => void leaveSession(),
    },
    {
      id: "sign-out",
      label: "Tanca la sessió",
      icon: "logout",
      onSelect: () => void leaveSession(),
    },
  ];
  if (profile.app_role === "admin") {
    items.push({
      id: "admin",
      label: "Administració",
      icon: "admin_panel_settings",
      onSelect: () => navigate("/admin"),
    });
  }

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
    <div className="relative shrink-0">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={label}
        title={profile.email}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
          }
        }}
        className="inline-flex h-10 w-10 items-center justify-center overflow-hidden rounded-full border border-outline-variant bg-primary-container text-on-primary-container transition-colors duration-200 hover:bg-primary-container/85 active:bg-primary-container/75 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
      >
        {shownAvatarUrl ? (
          <img
            src={shownAvatarUrl}
            alt=""
            referrerPolicy="no-referrer"
            className="h-full w-full object-cover"
            onError={() => setImageFailed(true)}
          />
        ) : initials ? (
          <span aria-hidden="true" className="text-label-large">
            {initials}
          </span>
        ) : (
          <Icon name="account_circle" filled className="text-[24px]" />
        )}
      </button>

      {open ? (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label={label}
          aria-orientation="vertical"
          onKeyDown={onMenuKeyDown}
          className="absolute right-0 top-full z-30 mt-2 w-72 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xs bg-surface-container py-2 shadow-elevation-2"
        >
          <div role="presentation" className="px-3 pb-2 pt-1">
            <p
              className="truncate text-title-small text-on-surface"
              title={profile.email}
            >
              {profile.email}
            </p>
            <p className="mt-0.5 text-label-medium text-on-surface-variant">
              {roleLabel}
            </p>
          </div>
          <div role="separator" className="my-1 h-px bg-outline-variant" />

          {items.map((item, index) => (
            <button
              key={item.id}
              ref={(element) => {
                itemRefs.current[index] = element;
              }}
              type="button"
              role="menuitem"
              tabIndex={-1}
              disabled={busy}
              onClick={() => {
                close(true);
                item.onSelect();
              }}
              className="flex h-12 w-full items-center gap-3 px-3 text-left text-label-large text-on-surface transition-colors hover:bg-on-surface/8 focus-visible:bg-on-surface/12 focus-visible:outline-none active:bg-on-surface/12 disabled:pointer-events-none disabled:opacity-[0.38]"
            >
              <Icon name={item.icon} className="text-[20px]" />
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
