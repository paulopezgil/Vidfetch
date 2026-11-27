import { useRef, useState } from "react";
import {
  Outlet,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import Icon from "../components/Icon";
import IconButton from "../components/IconButton";
import SearchBar from "../components/SearchBar";
import SegmentedButton from "../components/SegmentedButton";

const SECTIONS = [
  { value: "songs", label: "Cançons", icon: "music_note" },
  { value: "videos", label: "Vídeos", icon: "movie" },
  { value: "albums", label: "Àlbums", icon: "album" },
  { value: "artists", label: "Artistes", icon: "person" },
];

type Section = (typeof SECTIONS)[number]["value"];

const SECTION_VALUES = new Set<string>(SECTIONS.map((section) => section.value));

/**
 * The active section comes from the `/library/<section>` path so a deep link,
 * a refresh, or the browser back button always restores the same view. An
 * unknown or missing segment falls back to songs, the index redirect target.
 */
function sectionForPath(pathname: string): Section {
  const segment = pathname.split("/")[2] ?? "";
  return SECTION_VALUES.has(segment) ? (segment as Section) : "songs";
}

/**
 * Biblioteca: one destination for songs, videos, albums, and artists.
 *
 * The hub owns the section switch, the shared search query, and the page
 * padding; its child route renders the matching list embedded below the
 * switch. The query lives in the URL (`?q=`) so every section filters from the
 * same source of truth and the view survives a refresh or a deep link.
 */
export default function LibraryHub() {
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const [searchParams] = useSearchParams();
  const section = sectionForPath(pathname);
  const query = (searchParams.get("q") ?? "").trim();
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchInput, setSearchInput] = useState(query);
  const searchButtonRef = useRef<HTMLButtonElement>(null);

  function openSearch() {
    setSearchInput(query);
    setSearchOpen(true);
  }

  function closeSearch() {
    setSearchOpen(false);
    searchButtonRef.current?.focus();
  }

  function submitSearch() {
    const next = new URLSearchParams(searchParams);
    const trimmed = searchInput.trim();
    if (trimmed) next.set("q", trimmed);
    else next.delete("q");

    const nextSearch = next.toString();
    closeSearch();
    if (nextSearch !== searchParams.toString()) {
      navigate({ pathname, search: nextSearch ? `?${nextSearch}` : "" });
    }
  }

  function changeSection(value: string) {
    // Keep an active search when the user switches sections.
    navigate({ pathname: `/library/${value}`, search });
  }

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <div className="relative">
        <div className="flex items-center justify-between gap-2">
          <SegmentedButton
            label="Secció de la biblioteca"
            value={section}
            onChange={changeSection}
            options={SECTIONS}
            compact
            className="min-w-0 flex-1 sm:flex-none"
          />
          <IconButton
            buttonRef={searchButtonRef}
            label={
              query
                ? `Cerca a la biblioteca (activa: «${query}»)`
                : "Cerca a la biblioteca"
            }
            variant={query ? "filled" : "tonal"}
            ariaExpanded={searchOpen}
            onClick={openSearch}
            className="relative ml-auto"
          >
            <Icon name="search" className="text-[20px]" />
            {query ? (
              <span
                aria-hidden="true"
                className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-error ring-2 ring-surface"
              />
            ) : null}
          </IconButton>
        </div>

        {/* Absolute so the disclosed field covers the tabs without adding a
            second row to the page layout. */}
        {searchOpen ? (
          <div
            className="absolute inset-x-0 top-1/2 z-20 flex -translate-y-1/2 items-center gap-2 rounded-full bg-surface-container-high shadow-elevation-2"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.stopPropagation();
                closeSearch();
              }
            }}
          >
            <SearchBar
              autoFocus
              className="min-w-0 flex-1"
              value={searchInput}
              onChange={setSearchInput}
              onSubmit={submitSearch}
              label="Cerca a la biblioteca"
              placeholder="Cerca per títol, artista o àlbum"
            />
            <IconButton
              variant="tonal"
              label="Tanca la cerca"
              onClick={closeSearch}
            >
              <Icon name="close" className="text-[20px]" />
            </IconButton>
          </div>
        ) : null}
      </div>
      <Outlet />
    </div>
  );
}
