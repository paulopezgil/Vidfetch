import { NavLink } from "react-router-dom";
import Icon from "./Icon";
import { destinationsFor } from "../navigation";
import { useAuth } from "../auth/AuthProvider";
import Logo from "./Logo";

/** Material 3 navigation rail for medium windows. */
export default function NavigationRail() {
  const { profile } = useAuth();
  const destinations = destinationsFor(profile?.app_role === "admin");

  return (
    <nav
      aria-label="Navegació principal"
      className="hidden w-20 shrink-0 flex-col items-center gap-1 overflow-y-auto border-r border-outline-variant bg-surface py-4 md:flex lg:hidden"
    >
      <Logo className="mb-1 h-10 w-10" />

      {destinations.map((destination) => (
        <NavLink
          key={destination.to}
          to={destination.to}
          end={destination.end}
          title={destination.label}
          className="group flex w-16 flex-col items-center gap-1 py-1 text-label-medium"
        >
          {({ isActive }) => (
            <>
              <span
                className={`flex h-8 w-14 items-center justify-center rounded-full transition-colors ${
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
                className={`max-w-full truncate ${
                  isActive ? "text-on-surface" : "text-on-surface-variant"
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
