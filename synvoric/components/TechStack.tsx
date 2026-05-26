"use client";

import Image from "next/image";
import { useState } from "react";
import { techCategories } from "@/lib/site-data";

function techIconUrl(icon: string, color = "FFFFFF") {
  return `https://cdn.simpleicons.org/${icon}/${color}`;
}

export function TechStack() {
  const [activeId, setActiveId] = useState(techCategories[0].id);
  const active = techCategories.find((c) => c.id === activeId)!;

  return (
    <section id="technologies" className="bg-synvoric-navy py-20 md:py-28">
      <div className="mx-auto max-w-6xl px-6">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold uppercase tracking-widest text-synvoric-blue">
            Tech Stack
          </p>
          <h2 className="mt-3 text-3xl font-bold text-white md:text-4xl">
            Technologies Our Developers Master
          </h2>
        </div>

        <div className="mt-10 flex flex-wrap justify-center gap-2">
          {techCategories.map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={() => setActiveId(cat.id)}
              className={`rounded-full px-5 py-2 text-sm font-semibold transition-all duration-300 ${
                activeId === cat.id
                  ? "bg-synvoric-blue text-white shadow-lg shadow-synvoric-blue/30"
                  : "border border-white/15 text-slate-300 hover:border-synvoric-blue/50 hover:text-white"
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>

        <div
          key={activeId}
          className="animate-fade-in mt-12 grid grid-cols-3 gap-4 sm:grid-cols-4 md:grid-cols-6"
        >
          {active.items.map((tech, i) => (
            <div
              key={tech.name}
              className="tech-logo-card group flex flex-col items-center gap-3 rounded-2xl border border-white/8 bg-white/5 p-5 transition-all duration-300 hover:-translate-y-2 hover:border-synvoric-blue/40 hover:bg-white/10 hover:shadow-lg hover:shadow-synvoric-blue/10"
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <div className="tech-logo-float flex h-14 w-14 items-center justify-center rounded-xl bg-white/10 p-2.5 transition-transform duration-300 group-hover:scale-110">
                <Image
                  src={techIconUrl(tech.icon, tech.color ?? "FFFFFF")}
                  alt={tech.name}
                  width={40}
                  height={40}
                  className="h-9 w-9 object-contain"
                  unoptimized
                />
              </div>
              <span className="text-center text-xs font-medium text-slate-300 transition-colors group-hover:text-white">
                {tech.name}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
