import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        jc: {
          bg: "#faf7f4",
          "bg-deep": "#f0ebe6",
          card: "#ffffff",
          ink: "#1c1917",
          muted: "#57534e",
          border: "#e7e0da",
          brand: "#7c2d12",
          "brand-light": "#991b1b",
          accent: "#c2410c",
          "accent-hover": "#9a3412",
        },
      },
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        sans: ["var(--font-body)", "system-ui", "sans-serif"],
      },
      boxShadow: {
        jc: "0 1px 3px rgba(28, 25, 23, 0.06), 0 8px 24px rgba(28, 25, 23, 0.06)",
        "jc-lg": "0 4px 6px rgba(28, 25, 23, 0.04), 0 20px 40px rgba(28, 25, 23, 0.08)",
      },
    },
  },
  plugins: [],
} satisfies Config;
