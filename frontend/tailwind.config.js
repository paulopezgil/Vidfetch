/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0E1013",
        surface: {
          0: "#14161B",
          1: "#1A1D24",
          2: "#21242C",
        },
        line: {
          DEFAULT: "#2B2F3A",
          strong: "#363B48",
        },
        brand: {
          DEFAULT: "#6E7BFF",
          hover: "#8590FF",
          active: "#5A67E8",
        },
        "on-brand": "#0E1013",
        fg: {
          DEFAULT: "#E8EBF2",
          secondary: "#A0A7B5",
          muted: "#636B78",
        },
        success: "#3DD68C",
        info: "#5CA8F5",
        warning: "#F5B84D",
        danger: "#F06A6A",
      },
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
