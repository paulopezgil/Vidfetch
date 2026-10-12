import { NavLink } from "react-router-dom";
import Icon from "./Icon";
import { destinations } from "../navigation";

/** Material 3 navigation bar for compact windows. */
export default function NavigationBar() {
  return (
    <nav
      aria-label="Primary"
      className="flex h-20 shrink-0 items-stretch border-t border-outline-variant bg-surface-container pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      {destinations.map((destination) => (
        <NavLink
          key={destination.to}
          to={destination.to}
          end={destination.end}
          className="group flex min-w-0 flex-1 flex-col items-center justify-center gap-1 py-3 text-label-medium"
        >
          {({ isActive }) => (
            <>
              <span
                className={`flex h-8 w-16 items-center justify-center rounded-full transition-colors ${
                  isActive
                    ? "bg-secondary-container text-on-secondary-container"
                    : "text-on-surface-variant group-hover:bg-on-surface/8 group-active:bg-on-surface/12"
                }`}
              >
                <Icon
                  name={destination.icon}
                  filled={isActive}
                  className="text-[24px]"
                />
              </span>
              <span
                className={
                  isActive ? "text-on-surface" : "text-on-surface-variant"
                }
              >
                {destination.label}
              </span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
