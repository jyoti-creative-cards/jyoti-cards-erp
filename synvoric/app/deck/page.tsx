import Image from "next/image";
import { DeckToolbar, SlideFooter } from "@/components/DeckToolbar";
import {
  processSteps,
  services,
  stats,
  techCategories,
  clients,
} from "@/lib/site-data";

const TOTAL = 12;

const whySynvoric = [
  {
    title: "Rigorous Vetting",
    body: "Every developer passes technical assessments, live coding reviews, and communication screening before placement.",
  },
  {
    title: "Speed to Hire",
    body: "Average time from requirement to onboarded developer is two weeks — without compromising on quality.",
  },
  {
    title: "Flexible Models",
    body: "Staff augmentation, dedicated teams, or end-to-end delivery — scaled to your project stage and budget.",
  },
  {
    title: "Account Partnership",
    body: "A dedicated account manager ensures alignment, weekly check-ins, and seamless replacement if needed.",
  },
];

const engagementModels = [
  {
    title: "Staff Augmentation",
    body: "Individual developers embedded in your team, working within your tools, processes, and sprint cadence.",
  },
  {
    title: "Dedicated Teams",
    body: "A managed pod — tech lead, developers, QA — working exclusively on your product with weekly demos.",
  },
  {
    title: "Project Delivery",
    body: "End-to-end ownership from discovery and architecture through build, deploy, and maintenance.",
  },
];

export default function CapabilityDeck() {
  const frontend = services.find((s) => s.id === "frontend")!;
  const ai = services.find((s) => s.id === "ai")!;
  const web = services.find((s) => s.id === "web")!;
  const mobile = services.find((s) => s.id === "mobile")!;

  return (
    <>
      <DeckToolbar />
      <div className="deck-container">

        {/* 01 — Cover */}
        <div className="slide slide-cover">
          <div className="slide-inner">
            <Image src="/logo.png" alt="Synvoric" width={280} height={96} priority />
            <p className="cover-tagline">AI · Data · Engineering · Solutions</p>
            <p className="cover-subtitle">Capability Overview</p>
            <p className="cover-date">May 2026 · synvoric.com</p>
          </div>
          <SlideFooter n={1} total={TOTAL} />
        </div>

        {/* 02 — About */}
        <div className="slide">
          <div className="slide-inner">
            <p className="slide-eyebrow">About Us</p>
            <h2 className="slide-headline">Who We Are</h2>
            <div className="slide-rule" />
            <div className="two-col">
              <div className="slide-body">
                <p>
                  <strong>Synvoric</strong> is a professional IT staffing company
                  specializing in frontend developers and AI/ML engineers. We
                  partner with enterprises and growth-stage companies to deliver
                  vetted engineering talent for web applications, mobile apps, and
                  AI-powered products.
                </p>
                <p>
                  Founded on the belief that great software starts with great
                  people, we combine rigorous technical vetting with a
                  partnership-first approach — ensuring every placement drives
                  measurable business outcomes.
                </p>
              </div>
              <div>
                <p className="slide-eyebrow" style={{ marginBottom: 16 }}>At a Glance</p>
                <div className="deck-grid-2" style={{ gap: 12 }}>
                  {stats.map((s) => (
                    <div key={s.label} className="stat-block">
                      <div className="stat-val">{s.value}</div>
                      <div className="stat-lbl">{s.label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
          <SlideFooter n={2} total={TOTAL} />
        </div>

        {/* 03 — Section: Services */}
        <div className="slide slide-divider">
          <div className="slide-inner">
            <div className="section-num">02</div>
            <div className="section-title">Our Services</div>
            <div className="section-line" />
          </div>
          <SlideFooter n={3} total={TOTAL} />
        </div>

        {/* 04 — Services overview */}
        <div className="slide">
          <div className="slide-inner">
            <p className="slide-eyebrow">Services</p>
            <h2 className="slide-headline">Staffing &amp; Development Solutions</h2>
            <div className="slide-rule" />
            <div className="deck-grid-3">
              {services.map((s) => (
                <div key={s.id} className="deck-card">
                  <h4>{s.title}</h4>
                  <p>{s.summary}</p>
                </div>
              ))}
            </div>
          </div>
          <SlideFooter n={4} total={TOTAL} />
        </div>

        {/* 05 — Frontend detail */}
        <div className="slide">
          <div className="slide-inner">
            <p className="slide-eyebrow">Service Detail</p>
            <h2 className="slide-headline">{frontend.title}</h2>
            <div className="slide-rule" />
            <div className="two-col">
              <div className="slide-body">
                <p>{frontend.overview}</p>
                <ul className="bullet-list" style={{ marginTop: 16 }}>
                  {frontend.highlights.map((h) => (
                    <li key={h}>{h}</li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="slide-eyebrow" style={{ marginBottom: 12 }}>Roles We Staff</p>
                {frontend.roles.map((r) => (
                  <div key={r} className="client-chip" style={{ marginBottom: 6, display: "inline-block", marginRight: 6 }}>
                    {r}
                  </div>
                ))}
                <p className="slide-eyebrow" style={{ marginTop: 20, marginBottom: 12 }}>Key Technologies</p>
                <div className="client-row">
                  {frontend.tags.map((t) => (
                    <span key={t} className="client-chip">{t}</span>
                  ))}
                  <span className="client-chip">Vue.js</span>
                  <span className="client-chip">MERN</span>
                </div>
              </div>
            </div>
          </div>
          <SlideFooter n={5} total={TOTAL} />
        </div>

        {/* 06 — AI detail */}
        <div className="slide">
          <div className="slide-inner">
            <p className="slide-eyebrow">Service Detail</p>
            <h2 className="slide-headline">{ai.title}</h2>
            <div className="slide-rule" />
            <div className="two-col">
              <div className="slide-body">
                <p>{ai.overview}</p>
                <ul className="bullet-list" style={{ marginTop: 16 }}>
                  {ai.highlights.map((h) => (
                    <li key={h}>{h}</li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="slide-eyebrow" style={{ marginBottom: 12 }}>Roles We Staff</p>
                {ai.roles.map((r) => (
                  <div key={r} className="client-chip" style={{ marginBottom: 6, display: "inline-block", marginRight: 6 }}>
                    {r}
                  </div>
                ))}
                <p className="slide-eyebrow" style={{ marginTop: 20, marginBottom: 12 }}>Key Technologies</p>
                <div className="client-row">
                  {ai.tags.map((t) => (
                    <span key={t} className="client-chip">{t}</span>
                  ))}
                  <span className="client-chip">LangChain</span>
                  <span className="client-chip">MLOps</span>
                </div>
              </div>
            </div>
          </div>
          <SlideFooter n={6} total={TOTAL} />
        </div>

        {/* 07 — Web & Mobile */}
        <div className="slide">
          <div className="slide-inner">
            <p className="slide-eyebrow">Service Detail</p>
            <h2 className="slide-headline">Web &amp; Mobile App Development</h2>
            <div className="slide-rule" />
            <div className="deck-grid-2">
              <div className="deck-card">
                <h4>{web.title}</h4>
                <p>{web.overview}</p>
                <ul>
                  {web.highlights.map((h) => (
                    <li key={h}>{h}</li>
                  ))}
                </ul>
              </div>
              <div className="deck-card">
                <h4>{mobile.title}</h4>
                <p>{mobile.overview}</p>
                <ul>
                  {mobile.highlights.map((h) => (
                    <li key={h}>{h}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
          <SlideFooter n={7} total={TOTAL} />
        </div>

        {/* 08 — Section: Technologies */}
        <div className="slide slide-divider">
          <div className="slide-inner">
            <div className="section-num">03</div>
            <div className="section-title">Technologies</div>
            <div className="section-line" />
          </div>
          <SlideFooter n={8} total={TOTAL} />
        </div>

        {/* 09 — Tech stack */}
        <div className="slide">
          <div className="slide-inner">
            <p className="slide-eyebrow">Tech Stack</p>
            <h2 className="slide-headline">Technologies Our Developers Master</h2>
            <div className="slide-rule" />
            <div className="deck-grid-4">
              {techCategories.map((cat) => (
                <div key={cat.id} className="tech-col">
                  <h4>{cat.label}</h4>
                  <ul>
                    {cat.items.map((t) => (
                      <li key={t.name}>{t.name}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
          <SlideFooter n={9} total={TOTAL} />
        </div>

        {/* 10 — Why Synvoric */}
        <div className="slide">
          <div className="slide-inner">
            <p className="slide-eyebrow">Differentiators</p>
            <h2 className="slide-headline">Why Synvoric</h2>
            <div className="slide-rule" />
            <div className="deck-grid-2">
              {whySynvoric.map((p) => (
                <div key={p.title} className="pillar">
                  <h4>{p.title}</h4>
                  <p>{p.body}</p>
                </div>
              ))}
            </div>
          </div>
          <SlideFooter n={10} total={TOTAL} />
        </div>

        {/* 11 — Process + Clients */}
        <div className="slide">
          <div className="slide-inner">
            <p className="slide-eyebrow">Track Record</p>
            <h2 className="slide-headline">How We Work &amp; Who We Serve</h2>
            <div className="slide-rule" />
            <div className="deck-grid-4" style={{ marginBottom: 20 }}>
              {processSteps.map((s) => (
                <div key={s.step} className="process-step">
                  <div className="step-num">{s.step}</div>
                  <h4>{s.title}</h4>
                  <p>{s.description}</p>
                </div>
              ))}
            </div>
            <p className="slide-eyebrow" style={{ marginBottom: 10 }}>Selected Clients</p>
            <div className="client-row">
              {clients.map((c) => (
                <span key={c.name} className="client-chip">{c.name}</span>
              ))}
            </div>
          </div>
          <SlideFooter n={11} total={TOTAL} />
        </div>

        {/* 12 — Contact */}
        <div className="slide">
          <div className="slide-inner">
            <div className="contact-block">
              <p className="slide-eyebrow">Get in Touch</p>
              <h3>Let&apos;s Build Your Engineering Team</h3>
              <p className="slide-body" style={{ maxWidth: 480 }}>
                Share your requirements and we&apos;ll respond within one business
                day with matched candidates.
              </p>
              <p className="contact-email">palak.agrawal@synvoric.com</p>
              <p className="contact-web">www.synvoric.com</p>
              <div className="contact-detail">
                {engagementModels.map((m) => (
                  <div key={m.title}>
                    <strong>{m.title}</strong>
                    <span>{m.body}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <SlideFooter n={12} total={TOTAL} />
        </div>

      </div>
    </>
  );
}
