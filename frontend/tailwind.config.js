/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
        // Ensuring we have the specific shades requested, though standard Palette has them.
        // We can customize if needed.
    },
  },
  plugins: [],
}
