import { useState } from "react";
import Icon from "./Icon";

interface ThumbnailProps {
  src?: string | null;
  className?: string;
  /** Material Symbols name for the placeholder state. */
  icon?: string;
}

export default function Thumbnail({
  src,
  className = "",
  icon = "movie",
}: ThumbnailProps) {
  const [failed, setFailed] = useState(false);

  if (!src || failed) {
    return (
      <div
        className={`flex shrink-0 items-center justify-center rounded-lg bg-surface-container-high text-on-surface-variant ${className}`}
      >
        <Icon name={icon} className="text-[24px]" />
      </div>
    );
  }

  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className={`shrink-0 rounded-lg object-cover ${className}`}
    />
  );
}
