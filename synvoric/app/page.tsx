import Image from "next/image";
import Link from "next/link";
import { ClientMarquee } from "@/components/ClientMarquee";
import { ServicesSection } from "@/components/ServicesSection";
import { TechStack } from "@/components/TechStack";
import { processSteps, stats } from "@/lib/site-data";

const navLinks = [
  { href: "#services", label: "Services" },
  { href: "#technologies", label: "Technologies" },
  { href: "#clients", label: "Clients" },
  { href: "#contact", label: "Contact" },
];

export default function HomePage() {
  return (
    <>
      <header className="fixed inset-x-0 top-0 z-50 border-b border-slate-200/80 bg-white/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" className="flex items-center gap-3">
            <Image
              src="/logo.png"
              alt="Synvoric"
              width={140}
              height={48}
              className="h-10 w-auto"
              priority
            />
          </Link>
          <nav className="hidden items-center gap-7 lg:flex">
            {navLinks.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="text-sm font-medium text-slate-600 transition-colors hover:text-synvoric-blue"
              >
                {link.label}
              </a>
            ))}
          </nav>
          <a
            href="#contact"
            className="rounded-lg bg-synvoric-blue px-5 py-2.5 text-sm font-semibold text-white transition-all hover:bg-blue-700 hover:shadow-lg hover:shadow-synvoric-blue/25"
          >
            Hire Developers
          </a>
        </div>
      </header>

      <main>
        {/* Hero */}
        <section className="relative overflow-hidden bg-gradient-to-b from-slate-50 to-white pt-28 pb-16 md:pt-36 md:pb-24">
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-synvoric-blue/8 via-transparent to-transparent" />
          <div className="absolute -right-32 top-20 h-96 w-96 rounded-full bg-synvoric-blue/5 blur-3xl" />

          <div className="relative mx-auto max-w-6xl px-6">
            <div className="mx-auto max-w-3xl text-center">
              <p className="animate-fade-up mb-4 text-sm font-semibold uppercase tracking-widest text-synvoric-blue">
                Professional IT Staffing
              </p>
              <h1 className="animate-fade-up delay-100 text-4xl font-bold leading-tight tracking-tight text-synvoric-navy md:text-5xl lg:text-6xl">
                Frontend &amp;{" "}
                <span className="text-synvoric-blue">AI Developer</span> Staffing
              </h1>
              <p className="animate-fade-up delay-200 mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-slate-600">
                Synvoric places vetted frontend engineers and AI specialists
                for web apps, mobile (iOS &amp; Android), and full product
                delivery — on your timeline.
              </p>
              <div className="animate-fade-up delay-300 mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
                <a
                  href="#contact"
                  className="animate-pulse-glow inline-flex items-center justify-center rounded-lg bg-synvoric-blue px-8 py-3.5 text-base font-semibold text-white shadow-lg shadow-synvoric-blue/25 transition-all hover:bg-blue-700"
                >
                  Hire Developers
                </a>
                <a
                  href="#services"
                  className="inline-flex items-center justify-center rounded-lg border border-slate-300 bg-white px-8 py-3.5 text-base font-semibold text-synvoric-navy transition-all hover:border-synvoric-blue hover:text-synvoric-blue"
                >
                  Explore Services
                </a>
              </div>
            </div>

            <div className="animate-fade-up delay-400 mx-auto mt-20 grid max-w-4xl grid-cols-2 gap-6 md:grid-cols-4">
              {stats.map((stat) => (
                <div
                  key={stat.label}
                  className="rounded-2xl border border-slate-100 bg-white/80 p-5 text-center shadow-sm backdrop-blur transition-transform duration-300 hover:-translate-y-1 hover:shadow-md"
                >
                  <div className="text-3xl font-bold text-synvoric-navy md:text-4xl">
                    {stat.value}
                  </div>
                  <div className="mt-1 text-sm text-slate-500">{stat.label}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Clients */}
        <section id="clients" className="border-y border-slate-100 bg-slate-50 py-14">
          <div className="mx-auto max-w-6xl px-6">
            <h2 className="text-center text-2xl font-bold text-synvoric-navy md:text-3xl">
              Trusted by Leading Businesses
            </h2>
          </div>
          <div className="mt-8">
            <ClientMarquee />
          </div>
        </section>

        <ServicesSection />
        <TechStack />

        {/* Process — compact */}
        <section className="border-t border-slate-100 bg-slate-50 py-16">
          <div className="mx-auto max-w-6xl px-6">
            <h2 className="text-center text-2xl font-bold text-synvoric-navy">
              How We Work
            </h2>
            <div className="mt-10 grid grid-cols-2 gap-6 md:grid-cols-4">
              {processSteps.map((step) => (
                <div key={step.step} className="text-center">
                  <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-synvoric-blue text-sm font-bold text-white">
                    {step.step}
                  </div>
                  <h3 className="font-semibold text-synvoric-navy">{step.title}</h3>
                  <p className="mt-1 text-sm text-slate-500">{step.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Contact */}
        <section id="contact" className="py-20 md:py-28">
          <div className="mx-auto max-w-6xl px-6">
            <div className="mx-auto max-w-2xl rounded-2xl border border-slate-200 bg-gradient-to-br from-white to-slate-50 p-10 text-center shadow-sm md:p-14">
              <h2 className="text-3xl font-bold text-synvoric-navy md:text-4xl">
                Ready to Build Your Team?
              </h2>
              <p className="mt-4 text-lg text-slate-600">
                Share your requirements — we&apos;ll respond within one business
                day with matched candidates.
              </p>
              <a
                href="mailto:palak.agrawal@synvoric.com"
                className="mt-6 inline-flex items-center gap-2 text-lg font-semibold text-synvoric-blue transition-colors hover:text-blue-700"
              >
                palak.agrawal@synvoric.com
              </a>
              <div className="mt-8">
                <a
                  href="mailto:palak.agrawal@synvoric.com?subject=Developer%20Staffing%20Inquiry%20-%20Synvoric"
                  className="inline-flex items-center justify-center rounded-lg bg-synvoric-blue px-8 py-3.5 text-base font-semibold text-white transition-all hover:bg-blue-700 hover:shadow-lg hover:shadow-synvoric-blue/25"
                >
                  Get in Touch
                </a>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-200 bg-white py-10">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 md:flex-row">
          <Image
            src="/logo.png"
            alt="Synvoric"
            width={120}
            height={40}
            className="h-8 w-auto opacity-80"
          />
          <p className="text-sm text-slate-500">
            &copy; {new Date().getFullYear()} Synvoric · synvoric.com
          </p>
          <a
            href="mailto:palak.agrawal@synvoric.com"
            className="text-sm text-slate-500 transition-colors hover:text-synvoric-blue"
          >
            palak.agrawal@synvoric.com
          </a>
        </div>
      </footer>
    </>
  );
}
