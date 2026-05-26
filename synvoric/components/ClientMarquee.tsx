import Image from "next/image";
import { clients } from "@/lib/site-data";

export function ClientMarquee() {
  const track = [...clients, ...clients];

  return (
    <div className="marquee-mask relative overflow-hidden">
      <div className="animate-marquee flex w-max items-center gap-12 py-4">
        {track.map((client, i) => (
          <div
            key={`${client.name}-${i}`}
            className="group flex h-28 w-56 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white px-6 shadow-sm transition-all duration-300 hover:border-synvoric-blue/20 hover:shadow-md"
          >
            <Image
              src={client.logo}
              alt={client.name}
              width={200}
              height={80}
              className="max-h-20 w-auto object-contain opacity-85 transition-opacity duration-300 group-hover:opacity-100"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
