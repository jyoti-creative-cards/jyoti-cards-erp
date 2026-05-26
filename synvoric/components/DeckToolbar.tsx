"use client";

export function DeckToolbar() {
  return (
    <div className="deck-toolbar">
      <span>Synvoric · Capability Overview</span>
      <div>
        <a href="/">← Website</a>
        <button type="button" onClick={() => window.print()}>
          Download PDF
        </button>
      </div>
    </div>
  );
}

function SlideFooter({ n, total = 12 }: { n: number; total?: number }) {
  return (
    <div className="slide-footer">
      <span>Synvoric · Confidential</span>
      <span className="slide-num">
        {String(n).padStart(2, "0")} / {String(total).padStart(2, "0")}
      </span>
    </div>
  );
}

export { SlideFooter };
