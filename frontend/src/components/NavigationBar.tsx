import { NavLink } from "react-router-dom";
import Icon from "./Icon";
import { destinationsFor } from "../navigation";
import { useAuth } from "../auth/AuthProvider";

/** Material 3 navigation bar for compact windows. */
export default function NavigationBar() {
  const { profile } = useAuth();
  const destinations = destinationsFor(profile?.app_role === "admin");

  return (
    <nav
      aria-label="Navegació principal"
      className="flex h-24 shrink-0 items-stretch border-t border-outline-variant bg-surface-container pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      {destinations.map((destination) => (
        <NavLink
          key={destination.to}
          to={destination.to}
          end={destination.end}
          title={destination.label}
          className="group flex min-w-0 flex-1 flex-col items-center justify-center gap-1 overflow-hidden px-0.5 py-3 text-label-medium"
        >
          {({ isActive }) => (
            <>
              <span
                className={`flex h-9 w-full max-w-[4rem] items-center justify-center rounded-full transition-colors ${
                  isActive
                    ? "bg-secondary-container text-on-secondary-container"
                    : "text-on-surface-variant group-hover:bg-on-surface/8 group-active:bg-on-surface/12"
                }`}
              >
                <Icon
                  name={destination.icon}
                  filled={isActive}
                  className="text-[26px]"
                />
              </span>
              <span
                className={`max-w-full truncate px-1 text-center leading-tight ${
                  isActive
                    ? "text-on-surface"
                    : "text-on-surface-variant"
                }`}
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
