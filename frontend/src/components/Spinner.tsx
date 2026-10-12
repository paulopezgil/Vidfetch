import { Loader2 } from "lucide-react";

export default function Spinner({ className = "" }: { className?: string }) {
  return (
    <Loader2
      className={`h-4 w-4 animate-spin text-current ${className}`}
      aria-hidden="true"
    />
  );
}
