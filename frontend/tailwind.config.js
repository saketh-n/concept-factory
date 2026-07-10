/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Space Grotesk", "Inter", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
        pixel: ['"Press Start 2P"', "ui-monospace", "monospace"],
      },
      colors: {
        ink: "#0c1a3a",      // deep sky canvas
        well: "#0e1117",     // recessed surfaces: inputs, logs, code
      },
    },
  },
  plugins: [],
};
