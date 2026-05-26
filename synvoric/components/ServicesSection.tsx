"use client";

import { useEffect, useState } from "react";
import type { Service } from "@/lib/site-data";
import { services } from "@/lib/site-data";

export function ServicesSection() {
  const [active, setActive] = useState<Service | null>(null);

  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setActive(null);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKey);
    };
  }, [active]);

  return (
    <>
      <section id="services" className="py-20 md:py-28">
        <div className="mx-auto max-w-6xl px-6">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-sm font-semibold uppercase tracking-widest text-synvoric-blue">
              What We Offer
            </p>
            <h2 className="mt-3 text-3xl font-bold text-synvoric-navy md:text-4xl">
              Staffing &amp; Development Solutions
            </h2>
            <p className="mt-4 text-lg text-slate-600">
              Vetted engineers, matched to your stack and timeline — click any
              service to see how we deliver.
            </p>
          </div>

          <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {services.map((service) => (
              <button
                key={service.id}
                type="button"
                onClick={() => setActive(service)}
                className="group flex cursor-pointer flex-col rounded-2xl border border-slate-200 bg-white p-7 text-left transition-all duration-300 hover:-translate-y-1 hover:border-synvoric-blue/40 hover:shadow-xl hover:shadow-synvoric-blue/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-synvoric-blue"
              >
                <div className="mb-4 flex items-center justify-between">
                  <div className="h-1 w-10 rounded-full bg-synvoric-blue transition-all duration-300 group-hover:w-16" />
                  <span className="rounded-full bg-synvoric-blue/10 px-3 py-1 text-xs font-semibold text-synvoric-blue opacity-0 transition-opacity group-hover:opacity-100">
                    Learn more →
                  </span>
                </div>
                <h3 className="text-lg font-semibold text-synvoric-navy">
                  {service.title}
                </h3>
                <p className="mt-2 flex-1 text-sm leading-relaxed text-slate-600">
                  {service.summary}
                </p>
                <div className="mt-4 flex flex-wrap gap-1.5">
                  {service.tags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </button>
            ))}
          </div>
        </div>
      </section>

      {active && (
        <div
          className="fixed inset-0 z-[100] flex items-end justify-center p-4 sm:items-center sm:p-6"
          role="dialog"
          aria-modal="true"
          aria-labelledby="service-modal-title"
        >
          <div
            className="absolute inset-0 bg-synvoric-navy/60 backdrop-blur-sm animate-fade-in"
            onClick={() => setActive(null)}
          />
          <div className="animate-modal-up relative max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white shadow-2xl">
            <div className="sticky top-0 flex items-start justify-between border-b border-slate-100 bg-white px-7 py-5">
              <div>
                <p className="text-xs font-semibold uppercase tracking-widest text-synvoric-blue">
                  Service Detail
                </p>
                <h3
                  id="service-modal-title"
                  className="mt-1 text-xl font-bold text-synvoric-navy"
                >
                  {active.title}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setActive(null)}
                className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                aria-label="Close"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="space-y-6 px-7 py-6">
              <p className="leading-relaxed text-slate-600">{active.overview}</p>

              <div>
                <h4 className="mb-3 text-sm font-semibold uppercase tracking-wide text-synvoric-navy">
                  What We Deliver
                </h4>
                <ul className="space-y-2">
                  {active.highlights.map((item) => (
                    <li key={item} className="flex items-start gap-2.5 text-sm text-slate-600">
                      <svg className="mt-0.5 h-4 w-4 shrink-0 text-synvoric-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                      </svg>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <h4 className="mb-3 text-sm font-semibold uppercase tracking-wide text-synvoric-navy">
                  Roles We Staff
                </h4>
                <div className="flex flex-wrap gap-2">
                  {active.roles.map((role) => (
                    <span
                      key={role}
                      className="rounded-full border border-synvoric-blue/20 bg-synvoric-blue/5 px-3 py-1 text-xs font-medium text-synvoric-blue"
                    >
                      {role}
                    </span>
                  ))}
                </div>
              </div>

              <a
                href={`mailto:palak.agrawal@synvoric.com?subject=${encodeURIComponent(active.title + " — Synvoric Inquiry")}`}
                className="block w-full rounded-lg bg-synvoric-blue py-3 text-center text-sm font-semibold text-white transition-colors hover:bg-blue-700"
              >
                Request This Service
              </a>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
