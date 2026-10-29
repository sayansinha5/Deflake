/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#F0EFF2",
        surface: "#FFFFFF",
        sunken: "#F0EFF2",
        ice: "#D1E8FD",
        mint: "#54D088",
        border: { DEFAULT: "#E4E2EA", strong: "#C9C6D6" },
        ink: { DEFAULT: "#1C1C4A", secondary: "#4E5080", muted: "#8B8CA8" },
        accent: { DEFAULT: "#6C78D7", subtle: "#D1E8FD", ink: "#3F4CB8" },
        success: { DEFAULT: "#157A45", subtle: "#E5F8EE" },
        danger: { DEFAULT: "#C2414A", subtle: "#FDECEC" },
        warning: { DEFAULT: "#9A6708", subtle: "#FFF6E0" },
        neutral: "#5C5E86",
      },
    },
  },
  plugins: [],
};
