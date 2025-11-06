/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "#0F4C75",
          light: "#3282B8",
          dark: "#082746"
        },
        accent: "#FFC857"
      }
    }
  },
  plugins: []
};
