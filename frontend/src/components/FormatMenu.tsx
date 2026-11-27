import type { DownloadFormat } from "../types/v2";
import { PLAYLIST_HEIGHTS, SUPPORTED_HEIGHTS } from "../lib/formats";
import Icon from "./Icon";
import Menu, { type MenuAction } from "./Menu";

interface FormatMenuProps {
  value: DownloadFormat;
  onChange: (value: DownloadFormat) => void;
  /** Playlists offer caps because their items can have different heights. */
  isPlaylist: boolean;
  /** Heights present in a single video; ignored for playlists. */
  availableHeights?: number[];
  disabled?: boolean;
}

const triggerClassName =
  "inline-flex h-10 shrink-0 items-center gap-1 rounded-full border border-outline pl-3 pr-2 text-label-large text-on-surface transition-colors hover:bg-on-surface/8 active:bg-on-surface/12 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary focus-visible:ring-offset-2 focus-visible:ring-offset-surface disabled:pointer-events-none disabled:opacity-[0.38]";

/** Label for one profile; playlist heights are caps, not exact heights. */
function optionLabel(format: DownloadFormat, isPlaylist: boolean): string {
  if (format === "best") return "Millor disponible";
  if (format === "audio") return "Àudio (millor)";
  if (format === "mp3") return "MP3 320";
  return isPlaylist ? `Fins a ${format}` : format;
}

/** Heights to offer, highest first, limited to what the backend accepts. */
function offeredHeights(
  isPlaylist: boolean,
  availableHeights: number[],
): number[] {
  if (isPlaylist) return [...PLAYLIST_HEIGHTS];
  // A source may report an arbitrary height (576p, 432p); only emit caps the
  // backend knows. Nothing supported means the menu stays at best/audio/mp3.
  const present = new Set(availableHeights);
  return SUPPORTED_HEIGHTS.filter((height) => present.has(height));
}

/**
 * Material 3 menu trigger showing the current quality and a dropdown arrow.
 *
 * The popup itself is the shared `Menu` portal, so focus, keyboard and
 * viewport handling match the `•••` action menus.
 */
export default function FormatMenu({
  value,
  onChange,
  isPlaylist,
  availableHeights = [],
  disabled,
}: FormatMenuProps) {
  const actions: MenuAction[] = [
    {
      id: "best",
      label: optionLabel("best", isPlaylist),
      icon: "high_quality",
      selected: value === "best",
      onSelect: () => onChange("best"),
    },
    ...offeredHeights(isPlaylist, availableHeights).map((height) => {
      const format = `${height}p` as DownloadFormat;
      return {
        id: format,
        label: optionLabel(format, isPlaylist),
        icon: "hd",
        selected: value === format,
        onSelect: () => onChange(format),
      };
    }),
    {
      id: "audio",
      label: optionLabel("audio", isPlaylist),
      icon: "music_note",
      selected: value === "audio",
      onSelect: () => onChange("audio"),
    },
    {
      id: "mp3",
      label: optionLabel("mp3", isPlaylist),
      icon: "music_note",
      selected: value === "mp3",
      onSelect: () => onChange("mp3"),
    },
  ];

  // A previously selected height may not be offered for the current source;
  // the value still reads correctly and the backend treats it as a cap.
  const current =
    actions.find((action) => action.id === value)?.label ??
    optionLabel(value, isPlaylist);

  return (
    <Menu
      label={`Qualitat de descàrrega: ${current}`}
      actions={actions}
      disabled={disabled}
      triggerClassName={triggerClassName}
      trigger={
        <>
          <Icon name="tune" className="text-[18px] text-on-surface-variant" />
          <span className="whitespace-nowrap">{current}</span>
          <Icon
            name="arrow_drop_down"
            className="text-[20px] text-on-surface-variant"
          />
        </>
      }
    />
  );
}
