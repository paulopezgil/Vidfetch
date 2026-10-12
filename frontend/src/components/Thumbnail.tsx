import { useState, type ReactNode } from "react";
import { Clapperboard } from "lucide-react";

interface ThumbnailProps {
  src?: string | null;
  className?: string;
  icon?: ReactNode;
}

export default function Thumbnail({
  src,
  className = "",
  icon,
}: ThumbnailProps) {
  const [failed, setFailed] = useState(false);

  if (!src || failed) {
    return (
      <div
        className={`flex shrink-0 items-center justify-center bg-surface-2 text-fg-muted ${className}`}
      >
        {icon ?? <Clapperboard className="h-5 w-5" />}
      </div>
    );
  }

  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className={`shrink-0 object-cover ${className}`}
    />
  );
}
