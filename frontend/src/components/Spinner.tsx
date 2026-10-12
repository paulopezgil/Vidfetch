import Icon from "./Icon";

export default function Spinner({ className = "" }: { className?: string }) {
  return (
    <Icon
      name="progress_activity"
      className={`text-[20px] animate-spin ${className}`}
    />
  );
}
