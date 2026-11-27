import { Outlet, useLocation, useNavigate } from "react-router-dom";
import SegmentedButton from "../components/SegmentedButton";

const SECTIONS = [
  { value: "songs", label: "Cançons", icon: "music_note" },
  { value: "videos", label: "Vídeos", icon: "movie" },
  { value: "albums", label: "Àlbums", icon: "album" },
  { value: "artists", label: "Artistes", icon: "graphic_eq" },
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
 * The hub owns the section switch and the page padding; its child route
 * renders the matching list embedded below the switch.
 */
export default function LibraryHub() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const section = sectionForPath(pathname);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <SegmentedButton
        label="Secció de la biblioteca"
        value={section}
        onChange={(value) => navigate(`/library/${value}`)}
        options={SECTIONS}
      />
      <Outlet />
    </div>
  );
}
