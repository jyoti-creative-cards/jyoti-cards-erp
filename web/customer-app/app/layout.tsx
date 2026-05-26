import type { Metadata } from "next";
import { DM_Sans, Fraunces } from "next/font/google";
import "./globals.css";

const display = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const sans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Jyoti Creative Cards — Shop",
  description: "Browse our catalogue, build your order, and track deliveries.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable}`}>
      <body className={`${sans.className} jc-page-bg flex min-h-screen flex-col font-sans`}>
        <header className="sticky top-0 z-30 border-b border-jc-border/80 bg-jc-card/90 shadow-sm backdrop-blur-md">
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-0.5 bg-gradient-to-r from-jc-brand/0 via-jc-accent/60 to-jc-brand/0" aria-hidden />
          <div className="mx-auto flex max-w-6xl items-start gap-4 px-4 py-4 sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <div
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-jc-brand to-jc-accent font-display text-lg font-bold text-white shadow-md ring-2 ring-white/30"
                aria-hidden
              >
                JC
              </div>
              <div className="min-w-0">
                <p className="font-display text-xl font-semibold tracking-tight text-jc-brand sm:text-2xl">
                  Jyoti Creative Cards
                </p>
                <p className="truncate text-xs text-jc-muted sm:text-sm">Cards, stationery & creative supplies</p>
              </div>
            </div>
            <p className="hidden max-w-[11rem] text-right text-[11px] leading-snug text-jc-muted sm:block sm:text-xs">
              Quality you can feel · Orders on WhatsApp
            </p>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:py-10">{children}</main>
        <footer className="mt-auto border-t border-jc-border bg-jc-bg-deep/90 py-6 text-center text-xs text-jc-muted">
          © {new Date().getFullYear()} Jyoti Creative Cards · Thank you for shopping with us
        </footer>
      </body>
    </html>
  );
}
