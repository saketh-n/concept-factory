/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Space Grotesk", "Inter", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        ink: "#0a0e17", // page canvas
        panel: "#10151f", // raised surfaces: header, cards
        well: "#0c1017", // recessed surfaces: inputs, logs, code
        line: "rgba(255,255,255,0.08)", // hairline borders
        brand: {
          DEFAULT: "#34d399", // emerald 400 — primary actions
          soft: "#6ee7b7",
          deep: "#059669",
        },
        accent: "#a78bfa", // violet 400 — plans / agent activity
      },
      boxShadow: {
        card: "0 1px 2px rgba(0,0,0,0.4), 0 8px 24px -12px rgba(0,0,0,0.5)",
        pop: "0 4px 12px rgba(0,0,0,0.35), 0 24px 60px -20px rgba(0,0,0,0.6)",
      },
    },
  },
  plugins: [],
};
