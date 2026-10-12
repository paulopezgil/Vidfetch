import { NavLink } from "react-router-dom";
import Icon from "./Icon";
import { destinations } from "../navigation";

/** Material 3 navigation drawer for expanded windows. */
export default function NavigationDrawer() {
  return (
    <nav
      aria-label="Primary"
      className="hidden w-72 shrink-0 flex-col gap-1 border-r border-outline-variant bg-surface py-4 lg:flex"
    >
      <div className="mb-4 flex items-center gap-3 px-6">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-on-primary">
          <Icon name="smart_display" filled className="text-[22px]" />
        </div>
        <span className="text-title-large text-on-surface">Vidfetch</span>
      </div>

      {destinations.map((destination) => (
        <NavLink
          key={destination.to}
          to={destination.to}
          end={destination.end}
          className={({ isActive }) =>
            `mx-3 flex h-14 items-center gap-3 rounded-full px-4 text-label-large transition-colors ${
              isActive
                ? "bg-primary"
                : "hover:bg-on-surface/8 active:bg-on-surface/12"
            }`
          }
        >
          {({ isActive }) => (
            <>
              <Icon
                name={destination.icon}
                filled={isActive}
                className={`text-[24px] ${
                  isActive ? "text-on-primary" : "text-on-surface-variant"
                }`}
              />
              <span
                className={
                  isActive ? "text-on-primary" : "text-on-surface-variant"
                }
              >
                {destination.label}
              </span>
            </>
          )}
        </NavLink>
      ))}

      <div className="mt-auto px-6 py-4 text-body-small text-on-surface-variant">
        Powered by yt-dlp
      </div>
    </nav>
  );
}
