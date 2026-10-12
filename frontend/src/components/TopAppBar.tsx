import { useLocation } from "react-router-dom";
import Icon from "./Icon";
import { titleForPath } from "../navigation";

/** Material 3 top app bar. */
export default function TopAppBar() {
  const { pathname } = useLocation();

  return (
    <header className="flex h-16 shrink-0 items-center gap-3 bg-surface px-4 sm:px-6">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-on-primary lg:hidden">
        <Icon name="smart_display" filled className="text-[22px]" />
      </div>
      <h1 className="min-w-0 flex-1 truncate text-title-large text-on-surface">
        {titleForPath(pathname)}
      </h1>
    </header>
  );
}
