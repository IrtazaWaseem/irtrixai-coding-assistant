/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          dark: "#0f172a",
          surface: "#1e293b",
          border: "#334155",
          accent: "#3b82f6",
        },
      },
    },
  },
  plugins: [],
};
