/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Material 3 semantic color roles (RGB channels from CSS variables so
        // opacity modifiers such as bg-primary/8 keep working).
        primary: "rgb(var(--md-primary) / <alpha-value>)",
        "on-primary": "rgb(var(--md-on-primary) / <alpha-value>)",
        "primary-container": "rgb(var(--md-primary-container) / <alpha-value>)",
        "on-primary-container":
          "rgb(var(--md-on-primary-container) / <alpha-value>)",

        secondary: "rgb(var(--md-secondary) / <alpha-value>)",
        "on-secondary": "rgb(var(--md-on-secondary) / <alpha-value>)",
        "secondary-container":
          "rgb(var(--md-secondary-container) / <alpha-value>)",
        "on-secondary-container":
          "rgb(var(--md-on-secondary-container) / <alpha-value>)",

        tertiary: "rgb(var(--md-tertiary) / <alpha-value>)",
        "on-tertiary": "rgb(var(--md-on-tertiary) / <alpha-value>)",
        "tertiary-container":
          "rgb(var(--md-tertiary-container) / <alpha-value>)",
        "on-tertiary-container":
          "rgb(var(--md-on-tertiary-container) / <alpha-value>)",

        error: "rgb(var(--md-error) / <alpha-value>)",
        "on-error": "rgb(var(--md-on-error) / <alpha-value>)",
        "error-container": "rgb(var(--md-error-container) / <alpha-value>)",
        "on-error-container":
          "rgb(var(--md-on-error-container) / <alpha-value>)",

        background: "rgb(var(--md-background) / <alpha-value>)",
        "on-background": "rgb(var(--md-on-background) / <alpha-value>)",

        surface: "rgb(var(--md-surface) / <alpha-value>)",
        "on-surface": "rgb(var(--md-on-surface) / <alpha-value>)",
        "surface-variant": "rgb(var(--md-surface-variant) / <alpha-value>)",
        "on-surface-variant":
          "rgb(var(--md-on-surface-variant) / <alpha-value>)",
        "surface-dim": "rgb(var(--md-surface-dim) / <alpha-value>)",
        "surface-bright": "rgb(var(--md-surface-bright) / <alpha-value>)",
        "surface-container-lowest":
          "rgb(var(--md-surface-container-lowest) / <alpha-value>)",
        "surface-container-low":
          "rgb(var(--md-surface-container-low) / <alpha-value>)",
        "surface-container":
          "rgb(var(--md-surface-container) / <alpha-value>)",
        "surface-container-high":
          "rgb(var(--md-surface-container-high) / <alpha-value>)",
        "surface-container-highest":
          "rgb(var(--md-surface-container-highest) / <alpha-value>)",

        outline: "rgb(var(--md-outline) / <alpha-value>)",
        "outline-variant": "rgb(var(--md-outline-variant) / <alpha-value>)",

        "inverse-surface": "rgb(var(--md-inverse-surface) / <alpha-value>)",
        "inverse-on-surface":
          "rgb(var(--md-inverse-on-surface) / <alpha-value>)",
        "inverse-primary": "rgb(var(--md-inverse-primary) / <alpha-value>)",

        shadow: "rgb(var(--md-shadow) / <alpha-value>)",
        scrim: "rgb(var(--md-scrim) / <alpha-value>)",

        // Extended roles (Material Theme Builder custom colors). M3 has no
        // baseline success/warning, but operations need honest status color.
        success: "rgb(var(--md-success) / <alpha-value>)",
        "on-success": "rgb(var(--md-on-success) / <alpha-value>)",
        "success-container": "rgb(var(--md-success-container) / <alpha-value>)",
        "on-success-container":
          "rgb(var(--md-on-success-container) / <alpha-value>)",
        warning: "rgb(var(--md-warning) / <alpha-value>)",
        "on-warning": "rgb(var(--md-on-warning) / <alpha-value>)",
        "warning-container": "rgb(var(--md-warning-container) / <alpha-value>)",
        "on-warning-container":
          "rgb(var(--md-on-warning-container) / <alpha-value>)",
      },
      fontFamily: {
        sans: [
          "Roboto",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
      // Material 3 type scale (size / line-height / tracking / weight).
      fontSize: {
        "display-large": ["57px", { lineHeight: "64px", letterSpacing: "-0.25px" }],
        "display-medium": ["45px", { lineHeight: "52px", letterSpacing: "0px" }],
        "display-small": ["36px", { lineHeight: "44px", letterSpacing: "0px" }],
        "headline-large": ["32px", { lineHeight: "40px", letterSpacing: "0px" }],
        "headline-medium": ["28px", { lineHeight: "36px", letterSpacing: "0px" }],
        "headline-small": ["24px", { lineHeight: "32px", letterSpacing: "0px" }],
        "title-large": ["22px", { lineHeight: "28px", letterSpacing: "0px" }],
        "title-medium": ["16px", { lineHeight: "24px", letterSpacing: "0.15px", fontWeight: "500" }],
        "title-small": ["14px", { lineHeight: "20px", letterSpacing: "0.1px", fontWeight: "500" }],
        "body-large": ["16px", { lineHeight: "24px", letterSpacing: "0.5px" }],
        "body-medium": ["14px", { lineHeight: "20px", letterSpacing: "0.25px" }],
        "body-small": ["12px", { lineHeight: "16px", letterSpacing: "0.4px" }],
        "label-large": ["14px", { lineHeight: "20px", letterSpacing: "0.1px", fontWeight: "500" }],
        "label-medium": ["12px", { lineHeight: "16px", letterSpacing: "0.5px", fontWeight: "500" }],
        "label-small": ["11px", { lineHeight: "16px", letterSpacing: "0.5px", fontWeight: "500" }],
      },
      // Material 3 shape scale.
      borderRadius: {
        none: "0px",
        xs: "4px",
        sm: "8px",
        md: "12px",
        lg: "16px",
        xl: "28px",
        full: "9999px",
      },
      boxShadow: {
        "elevation-1":
          "0 1px 2px 0 rgb(var(--md-shadow) / 0.30), 0 1px 3px 1px rgb(var(--md-shadow) / 0.15)",
        "elevation-2":
          "0 1px 2px 0 rgb(var(--md-shadow) / 0.30), 0 2px 6px 2px rgb(var(--md-shadow) / 0.15)",
        "elevation-3":
          "0 1px 3px 0 rgb(var(--md-shadow) / 0.30), 0 4px 8px 3px rgb(var(--md-shadow) / 0.15)",
      },
      // Material 3 state-layer opacities (hover 8%, pressed 12%, scrim 32%).
      opacity: {
        8: "0.08",
        12: "0.12",
        16: "0.16",
        32: "0.32",
      },
    },
  },
  plugins: [],
};
