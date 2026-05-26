import type { Metadata } from "next";
import "./deck.css";

export const metadata: Metadata = {
  title: "Synvoric | Capability Overview",
  description: "Synvoric capability deck — Frontend & AI developer staffing.",
  robots: { index: false, follow: false },
};

export default function DeckLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <div className="deck-root">{children}</div>;
}
