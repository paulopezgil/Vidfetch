import { useId } from "react";

/**
 * Inline rendering of the Vidfetch app mark.
 *
 * The same artwork lives in `public/favicon.svg`, but the logo is inline so it
 * can never disappear when the static file is missing or the app is offline.
 * Gradient/filter ids are suffixed per instance to avoid collisions when the
 * mark appears more than once in a document.
 */
export default function Logo({ className = "" }: { className?: string }) {
  const uid = useId().replace(/:/g, "");
  const bgGradient = `logo-bg-${uid}`;
  const symbolGradient = `logo-symbol-${uid}`;
  const dropShadow = `logo-shadow-${uid}`;

  return (
    <svg
      viewBox="0 0 512 512"
      role="presentation"
      aria-hidden="true"
      focusable="false"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={bgGradient} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#FF3B30" />
          <stop offset="50%" stopColor="#E02424" />
          <stop offset="100%" stopColor="#9B1C1C" />
        </linearGradient>

        <linearGradient id={symbolGradient} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#FFFFFF" />
          <stop offset="100%" stopColor="#F3F4F6" />
        </linearGradient>

        <filter
          id={dropShadow}
          x="-20%"
          y="-20%"
          width="140%"
          height="140%"
        >
          <feDropShadow
            dx="0"
            dy="12"
            stdDeviation="16"
            floodColor="#000000"
            floodOpacity="0.3"
          />
        </filter>
      </defs>

      <rect
        x="32"
        y="32"
        width="448"
        height="448"
        rx="105"
        fill={`url(#${bgGradient})`}
      />
      <rect
        x="32"
        y="32"
        width="448"
        height="448"
        rx="105"
        fill="#FFFFFF"
        fillOpacity="0.06"
      />
      <path
        d="M 288 112 L 176 272 H 264 L 224 400 L 336 240 H 248 Z"
        fill={`url(#${symbolGradient})`}
        filter={`url(#${dropShadow})`}
        strokeLinejoin="round"
      />
    </svg>
  );
}
