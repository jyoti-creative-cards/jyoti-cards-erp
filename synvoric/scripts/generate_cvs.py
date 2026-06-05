#!/usr/bin/env python3
"""
Generate 6 synthetic CVs — all 5+ years experience, detailed projects.

3 Frontend Developers (MERN, Flutter/Mobile, Angular)
3 UX/UI Designers (SaaS, Mobile, Product)

All output PDFs are saved in synvoric/assets/CV/.
"""

from __future__ import annotations
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets" / "CV"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NAVY = HexColor("#0A1628")
BLUE = HexColor("#0066FF")
SLATE = HexColor("#64748B")
BODY = HexColor("#1F2937")
BORDER = HexColor("#E2E8F0")

PAGE_W, PAGE_H = A4
ML = 0.6 * inch
MR = 0.6 * inch
CW = PAGE_W - ML - MR


def wrap_text(text: str, font: str, size: int, width: float) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        candidate = (current + " " + word).strip()
        if stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_text(c, x, y, text, font="Helvetica", size=10, color=BODY, max_width=None):
    c.setFont(font, size)
    c.setFillColor(color)
    if max_width is None:
        c.drawString(x, y, text)
        return y - (size + 2)
    for line in wrap_text(text, font, size, max_width):
        c.drawString(x, y, line)
        y -= size + 2
    return y


def draw_section(c, y, title):
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(BLUE)
    c.drawString(ML, y, title.upper())
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(ML, y - 4, ML + CW, y - 4)
    return y - 18


def draw_header(c, name, role):
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 0.95 * inch, PAGE_W, 0.95 * inch, fill=1, stroke=0)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 22)
    c.drawString(ML, PAGE_H - 0.50 * inch, name)
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(ML, PAGE_H - 0.75 * inch, role)
    return PAGE_H - 1.20 * inch


def draw_bullet(c, x, y, text, indent=10, font="Helvetica", size=9.5, max_width=None):
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "•")
    c.setFillColor(BODY)
    if max_width is None:
        max_width = CW - indent
    return draw_text(c, x + indent, y, text, font=font, size=size, max_width=max_width)


def draw_keyvalue(c, y, k, v, k_width=1.4 * inch):
    c.setFont("Helvetica-Bold", 9.5)
    c.setFillColor(NAVY)
    c.drawString(ML, y, k)
    c.setFont("Helvetica", 9.5)
    c.setFillColor(BODY)
    end_y = draw_text(c, ML + k_width, y, v, size=9.5, max_width=CW - k_width)
    return end_y


def render_cv(data: dict, out_path: Path):
    c = canvas.Canvas(str(out_path), pagesize=A4)
    c.setTitle(f"{data['name']} — {data['role']}")
    c.setAuthor(data["name"])

    y = draw_header(c, data["name"], data["role"])

    def maybe_new_page(y, min_y=80):
        if y < min_y:
            c.showPage()
            return PAGE_H - 0.5 * inch
        return y

    # Profile
    y = draw_section(c, y, "Profile")
    y = draw_text(c, ML, y, data["profile"], size=10, max_width=CW)
    y -= 8

    # Skills
    y = draw_section(c, y, "Skills")
    for group, skills in data["skills"]:
        y = draw_keyvalue(c, y, group, skills)
        y -= 3
    y -= 6

    # Experience
    y = draw_section(c, y, "Professional Experience")
    for exp in data["experience"]:
        y = maybe_new_page(y, 120)
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(NAVY)
        c.drawString(ML, y, exp["title"])
        c.setFont("Helvetica", 9)
        c.setFillColor(SLATE)
        period_str = f"{exp['employer']}  |  {exp['period']}"
        c.drawRightString(ML + CW, y, period_str)
        y -= 14
        for bullet in exp["bullets"]:
            y = maybe_new_page(y, 60)
            y = draw_bullet(c, ML, y, bullet, size=9.5, max_width=CW - 14)
            y -= 1
        y -= 6

    # Projects
    if data.get("projects"):
        y = maybe_new_page(y, 120)
        y = draw_section(c, y, "Selected Projects")
        for proj in data["projects"]:
            y = maybe_new_page(y, 80)
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(NAVY)
            c.drawString(ML, y, proj["name"])
            c.setFont("Helvetica-Oblique", 8.5)
            c.setFillColor(BLUE)
            c.drawString(ML + stringWidth(proj["name"], "Helvetica-Bold", 10) + 6, y,
                         f"— {proj['stack']}")
            y -= 12
            y = draw_text(c, ML + 10, y, proj["description"], size=9, max_width=CW - 10)
            y -= 6

    # Education
    if data.get("education"):
        y = maybe_new_page(y, 80)
        y = draw_section(c, y, "Education")
        for edu in data["education"]:
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(NAVY)
            c.drawString(ML, y, edu["degree"])
            c.setFont("Helvetica", 9)
            c.setFillColor(SLATE)
            c.drawRightString(ML + CW, y, edu["period"])
            y -= 12
            c.setFont("Helvetica", 9.5)
            c.setFillColor(BODY)
            c.drawString(ML + 10, y, edu["institution"])
            y -= 14

    # Certifications
    if data.get("certifications"):
        y = maybe_new_page(y, 80)
        y = draw_section(c, y, "Certifications")
        for cert in data["certifications"]:
            y = draw_bullet(c, ML, y, cert, size=9.5, max_width=CW - 14)
            y -= 1

    c.showPage()
    c.save()


# ── data: 3 Frontend Developers ────────────────────────────────────────

FRONTEND_DEVS = [
    {
        "filename": "Rohan-Verma-Frontend-Developer-MERN.pdf",
        "name": "Rohan Verma",
        "role": "Senior Frontend Developer (MERN Stack)",
        "profile": (
            "Full-stack-oriented Senior Frontend Developer with 7+ years of experience architecting "
            "and delivering high-scale responsive web applications on the MERN stack. Deep expertise "
            "in React with Redux Toolkit, Server-Side Rendering with Next.js, Node.js microservices, "
            "and MongoDB schema design. Proven track record of leading frontend teams, establishing "
            "design systems, and driving significant performance improvements across enterprise "
            "SaaS, FinTech, and EdTech products."
        ),
        "skills": [
            ("Frontend", "React.js, Next.js 14, Redux Toolkit, RTK Query, TypeScript, JavaScript (ES2022+), Tailwind CSS, Styled Components, HTML5, CSS3"),
            ("Backend", "Node.js, Express.js, REST APIs, GraphQL, tRPC, WebSockets"),
            ("Database", "MongoDB, Mongoose, PostgreSQL, Redis, Prisma ORM"),
            ("Testing", "Jest, React Testing Library, Cypress, Playwright, Storybook"),
            ("DevOps", "Docker, GitHub Actions, AWS (S3, CloudFront, Lambda), Vercel, Nginx"),
            ("Tooling", "Webpack, Vite, Turborepo, ESLint, Prettier, Husky"),
        ],
        "experience": [
            {
                "title": "Lead Frontend Engineer",
                "employer": "Confidential Product Company",
                "period": "07/2021 – Present",
                "bullets": [
                    "Architected and led the full frontend rebuild of a multi-tenant SaaS analytics platform serving 500+ enterprise clients, migrating from a legacy AngularJS monolith to a React + Redux Toolkit + Next.js codebase; reduced initial load time by 52%.",
                    "Designed and published an internal component library (Storybook + Tailwind) with 120+ reusable components, adopted across 6 product squads and cutting feature delivery time by 35%.",
                    "Introduced RTK Query for server-state management, replacing 8,000+ lines of hand-rolled fetch logic with a uniform caching and invalidation layer.",
                    "Drove a WebSockets-based real-time notification system serving 10k concurrent users with sub-200ms delivery latency.",
                    "Established frontend engineering standards: PR review checklist, accessibility audits (WCAG 2.1 AA), performance budgets, and automated Lighthouse CI gates.",
                    "Managed and mentored a team of 5 frontend engineers — conducted weekly 1-on-1s, quarterly growth plans, and bi-weekly architecture reviews.",
                ],
            },
            {
                "title": "Senior Frontend Developer",
                "employer": "Software Services Firm",
                "period": "03/2019 – 06/2021",
                "bullets": [
                    "Delivered 12+ customer-facing portals for FinTech, EdTech, and Logistics clients using React.js and Next.js with SSR/ISR patterns.",
                    "Built a real-time order-tracking module with Google Maps API and WebSocket push updates, reducing support tickets by 28%.",
                    "Implemented JWT + refresh-token auth flows, RBAC, OAuth 2.0 social logins, and Stripe + Razorpay payment integrations across 4 projects.",
                    "Reduced average bundle size by 41% through route-based code splitting, tree-shaking, and Webpack bundle analysis.",
                    "Introduced Cypress E2E tests covering 80% of critical user flows; caught 15 regressions before production in the first quarter.",
                ],
            },
            {
                "title": "Frontend Developer",
                "employer": "Early-Stage EdTech Startup",
                "period": "06/2017 – 02/2019",
                "bullets": [
                    "Built an adaptive quiz engine in React with branching logic, timed assessments, and real-time score analytics for 20k+ students.",
                    "Developed a live-classroom feature using WebRTC (peer-to-peer video) and Socket.IO (chat + whiteboard sync).",
                    "Integrated a markdown-based course authoring tool with custom preview renderer and media upload to AWS S3.",
                ],
            },
        ],
        "projects": [
            {
                "name": "Multi-Tenant SaaS Analytics Platform",
                "stack": "React, Redux Toolkit, Next.js, Node.js, MongoDB, Recharts, WebSockets",
                "description": (
                    "Enterprise analytics dashboard for 500+ tenants with role-based views, real-time KPI widgets, "
                    "drill-down reports, CSV/PDF export, and configurable alerting. Handles 2M+ events/day."
                ),
            },
            {
                "name": "Internal Design System",
                "stack": "React, Tailwind CSS, Storybook, Chromatic, Figma Tokens",
                "description": (
                    "120-component design system with semantic design tokens, dark-mode support, WCAG 2.1 AA "
                    "compliance, automated visual regression testing via Chromatic, and a documentation site."
                ),
            },
            {
                "name": "E-commerce Marketplace (B2B)",
                "stack": "Next.js 14, tRPC, PostgreSQL, Prisma, Stripe, Tailwind",
                "description": (
                    "Full-stack B2B marketplace with SSR product catalogue, multi-vendor checkout, "
                    "subscription billing, admin order management, and seller analytics dashboard."
                ),
            },
            {
                "name": "Live Classroom Platform",
                "stack": "React, WebRTC, Socket.IO, Node.js, Redis, AWS S3",
                "description": (
                    "Real-time virtual classroom with peer-to-peer video (WebRTC), shared whiteboard, "
                    "live chat, quiz injection mid-session, and session recording with playback."
                ),
            },
            {
                "name": "Internal CMS & Headless API",
                "stack": "React, Node.js, MongoDB, GraphQL, AWS CloudFront",
                "description": (
                    "Headless CMS with WYSIWYG editor, media library, granular publishing workflows, "
                    "role-based content access, and a GraphQL delivery API serving 3 frontend products."
                ),
            },
        ],
        "education": [
            {
                "degree": "B.Tech, Computer Science",
                "institution": "Visvesvaraya Technological University, Karnataka",
                "period": "2013 – 2017",
            },
        ],
        "certifications": [
            "AWS Certified Developer – Associate",
            "MongoDB for JavaScript Developers — MongoDB University",
            "Advanced React & Next.js — Meta (Coursera)",
            "Node.js Application Performance — Linux Foundation",
        ],
    },
    {
        "filename": "Priya-Sharma-Frontend-Developer-Flutter.pdf",
        "name": "Priya Sharma",
        "role": "Senior Mobile Developer (Flutter & React Native)",
        "profile": (
            "Senior Mobile Frontend Developer with 6+ years of end-to-end experience shipping "
            "cross-platform consumer and enterprise apps on Flutter and React Native. Expert in "
            "offline-first architecture, state management, native module integration, and App "
            "Store/Play Store release pipelines. Led mobile teams of up to 4 engineers across "
            "HealthTech, FinTech, and D2C verticals. Comfortable bridging to backend teams "
            "and owning full-stack feature delivery on mobile."
        ),
        "skills": [
            ("Cross-Platform", "Flutter 3.x, Dart, React Native 0.73+, Expo SDK 50, TypeScript"),
            ("State Management", "Riverpod, Bloc/Cubit, Redux Toolkit, Zustand, Provider"),
            ("Native Bridges", "Platform Channels (Flutter), JSI/TurboModules (RN), Swift, Kotlin"),
            ("Backend / APIs", "REST, GraphQL, Firebase (Auth, Firestore, FCM, Remote Config), Supabase"),
            ("DevOps", "Fastlane, GitHub Actions, App Center, Bitrise, Sentry, Datadog"),
            ("Tooling", "Figma (handoff), Xcode, Android Studio, Git, Detox, Flutter Driver"),
        ],
        "experience": [
            {
                "title": "Lead Mobile Developer",
                "employer": "Confidential Health-Tech Scale-up",
                "period": "01/2022 – Present",
                "bullets": [
                    "Led a team of 4 mobile engineers building and scaling a Flutter wellness app from 20k to 350k+ MAU across iOS and Android.",
                    "Architected an offline-first data layer using Hive + background isolates, enabling full app functionality with intermittent connectivity.",
                    "Shipped native integrations for Apple HealthKit, Google Fit, and Garmin Connect via Flutter platform channels.",
                    "Reduced cold-start time by 34% through deferred widget initialization, Ahead-of-Time compilation tuning, and lazy route loading.",
                    "Built a CI/CD pipeline with Fastlane + GitHub Actions delivering weekly OTA releases and bi-weekly store submissions with zero manual steps.",
                    "Introduced Bloc + Riverpod architecture patterns; reduced state-related crash rate by 61% within two sprints of rollout.",
                    "Partnered with product and design on a complete onboarding redesign — day-7 retention improved from 38% to 57%.",
                ],
            },
            {
                "title": "Senior React Native Developer",
                "employer": "D2C Brand (Confidential)",
                "period": "04/2020 – 12/2021",
                "bullets": [
                    "Owned the full React Native codebase of a fashion shopping app generating ₹12 Cr/month GMV across iOS and Android.",
                    "Integrated Razorpay, Cashfree, and UPI Collect payment flows; built address book, order tracking, and loyalty points UI.",
                    "Built a dynamic home screen driven by a Firebase Remote Config–powered JSON schema, enabling zero-downtime A/B testing of layouts.",
                    "Implemented deep-link–driven push notifications (FCM) for cart recovery; contributed to a 19% uplift in 30-day repeat purchases.",
                    "Coordinated bi-weekly App Store / Play Store submissions, ASO updates, and production crash triage in Sentry.",
                ],
            },
            {
                "title": "Mobile Developer",
                "employer": "Product Studio (Confidential)",
                "period": "06/2018 – 03/2020",
                "bullets": [
                    "Delivered 9 cross-platform mobile apps across fitness, travel, finance, and EdTech verticals as sole or co-developer.",
                    "Established reusable component library and project scaffold for React Native that cut bootstrapping time by 60% across engagements.",
                    "Mentored 2 junior developers on state management patterns and platform-specific testing approaches.",
                ],
            },
        ],
        "projects": [
            {
                "name": "Wellness Companion App (350k MAU)",
                "stack": "Flutter, Riverpod, Hive, Firebase, HealthKit, Google Fit",
                "description": (
                    "Daily mood tracking, sleep insights, guided breathing, and wearable sync. Offline-first with "
                    "background sync. Released on App Store and Play Store with 4.7★ rating."
                ),
            },
            {
                "name": "D2C Fashion Shopping App",
                "stack": "React Native, Redux Toolkit, Firebase, Razorpay, Cashfree",
                "description": (
                    "Full-featured shopping app with personalised feed, PLP/PDP, cart, wishlist, "
                    "multi-payment checkout, order tracking, and dynamic home screen via Remote Config."
                ),
            },
            {
                "name": "Hyperlocal Delivery App (Two-Sided)",
                "stack": "React Native, Expo, Firebase, Mapbox, Stripe",
                "description": (
                    "Customer and delivery-partner apps sharing a Mapbox real-time tracking layer, "
                    "live ETA updates, in-app chat, and proof-of-delivery photo capture."
                ),
            },
            {
                "name": "AI Chat Assistant (Mobile)",
                "stack": "Flutter, Dart, OpenAI Streaming API, Riverpod, SQLite",
                "description": (
                    "GPT-4-powered conversational assistant with streaming responses, per-user prompt "
                    "presets, offline conversation history, and token usage dashboard."
                ),
            },
            {
                "name": "Corporate Field-Force App",
                "stack": "Flutter, Bloc, REST APIs, Google Maps, SQLite",
                "description": (
                    "Offline-capable field-force management app for 1,200 agents — daily task lists, "
                    "geo-fenced check-ins, customer visit reports, and manager approval workflows."
                ),
            },
        ],
        "education": [
            {
                "degree": "B.E., Information Technology",
                "institution": "Savitribai Phule Pune University",
                "period": "2014 – 2018",
            },
        ],
        "certifications": [
            "Flutter Development Bootcamp — App Brewery (Udemy)",
            "Firebase in a Weekend — Google Developers",
            "React Native — The Practical Guide (Udemy)",
            "Mobile App Security — OWASP Foundation",
        ],
    },
    {
        "filename": "Arjun-Mehta-Frontend-Developer-Angular.pdf",
        "name": "Arjun Mehta",
        "role": "Principal Frontend Engineer (Angular / Enterprise)",
        "profile": (
            "Principal Frontend Engineer with 8 years of deep Angular expertise, specialising in "
            "large-scale enterprise web applications in Banking, Insurance, and ERP domains. "
            "Expert in TypeScript, RxJS reactive patterns, NgRx state architecture, and Nx "
            "monorepo governance. Led frontend chapters of 8–10 engineers, drove micro-frontend "
            "adoption, and championed accessibility and performance standards across multi-product "
            "platform suites."
        ),
        "skills": [
            ("Angular", "Angular 12–17, RxJS 7+, NgRx, Angular Material, Standalone Components, Signals"),
            ("Languages", "TypeScript 5+, JavaScript (ES2022+), HTML5, CSS3, Sass, SCSS"),
            ("Architecture", "Nx Monorepo, Module Federation (Micro-frontends), Storybook, Design Tokens"),
            ("Testing", "Jasmine, Karma, Jest, Cypress, Playwright, Accessibility (axe-core)"),
            ("DevOps", "GitLab CI/CD, Jenkins, Docker, AWS (EC2, S3, CloudFront), Azure DevOps"),
            ("Tooling", "Webpack 5, Vite, ESLint, Prettier, SonarQube, Husky, Chromatic"),
        ],
        "experience": [
            {
                "title": "Principal Frontend Engineer",
                "employer": "Confidential Banking Software Vendor",
                "period": "03/2020 – Present",
                "bullets": [
                    "Architected an Angular 16 Nx monorepo serving 9 product modules — retail banking, corporate banking, treasury, trade finance, cards, and wealth — used by 40+ bank clients globally.",
                    "Designed and enforced micro-frontend strategy using Webpack Module Federation, allowing 5 independent teams to release without cross-team coordination.",
                    "Introduced Angular Signals (v17) for fine-grained reactivity in high-frequency data grids — reduced unnecessary re-renders by 73% in live position dashboards.",
                    "Established the internal Design System: 150+ components, design-token sync from Figma via Tokens Studio, automated visual regression with Chromatic.",
                    "Led accessibility uplift programme — brought all 9 modules from WCAG 2.0 A to 2.1 AA compliance; integrated axe-core into the CI pipeline.",
                    "Managed a frontend chapter of 9 engineers; ran biweekly architecture guilds, quarterly roadmap planning, and hiring panels.",
                ],
            },
            {
                "title": "Lead Frontend Developer",
                "employer": "Insurance Technology Company",
                "period": "05/2017 – 02/2020",
                "bullets": [
                    "Led frontend delivery for a commercial lines underwriting platform processing ₹2,400 Cr annual premium — 80+ dynamic reactive forms using Angular Reactive Forms.",
                    "Reduced page render time by 55% via OnPush change detection, virtual scrolling (CDK), and trackBy optimisations in complex data grids.",
                    "Drove a 14-month AngularJS-to-Angular 12 migration with zero downtime — strangler-fig pattern, feature-flag gating, and parallel running of old/new modules.",
                    "Built a rules-based form-generation engine that eliminated 60% of hand-coded form templates.",
                    "Introduced Cypress E2E suite covering 300+ test cases across underwriting, endorsement, and claims journeys.",
                ],
            },
            {
                "title": "Frontend Developer",
                "employer": "Enterprise Software Consultancy",
                "period": "07/2015 – 04/2017",
                "bullets": [
                    "Delivered 7 Angular 2/4 enterprise apps for Banking and HR clients across Europe and India.",
                    "Built a reusable data-grid component supporting virtual scrolling, inline editing, multi-sort, and Excel export — used across 5 client projects.",
                    "Contributed to open-source Angular Material extensions; PR merged with 2.3k GitHub stars.",
                ],
            },
        ],
        "projects": [
            {
                "name": "Corporate Banking Workbench",
                "stack": "Angular 17, NgRx, RxJS, Module Federation, Angular Material",
                "description": (
                    "Multi-product workbench for 1,800+ relationship managers — complex approval flows, "
                    "real-time position dashboards, audit trails, SWIFT message composer, and trade "
                    "finance document management."
                ),
            },
            {
                "name": "Micro-Frontend Platform Shell",
                "stack": "Angular, Webpack Module Federation, Nx, Azure DevOps",
                "description": (
                    "Host shell orchestrating 8 independently-deployed Angular micro-frontends with shared "
                    "auth context, event bus, and design-token theming. Enables per-team release cadence."
                ),
            },
            {
                "name": "Underwriting Workbench",
                "stack": "Angular, Reactive Forms, NgRx, Jasmine/Karma, Cypress",
                "description": (
                    "80+ reactive forms covering commercial lines risk capture, pricing, referrals, and "
                    "policy issuance. Rules engine drives conditional field visibility and validation."
                ),
            },
            {
                "name": "Claims Processing Portal",
                "stack": "Angular, Spring Boot APIs, PostgreSQL, Cypress",
                "description": (
                    "End-to-end claims portal handling 40k claims/day with role-specific screens for "
                    "assessors, supervisors, fraud analysts, and finance teams."
                ),
            },
            {
                "name": "Enterprise Design System",
                "stack": "Angular, Storybook, Tokens Studio, Chromatic, Figma",
                "description": (
                    "Themable component library (150+ components) used across 6 product lines. "
                    "Design-token pipeline syncs Figma variables to SCSS variables and Angular theme "
                    "objects on every Figma publish."
                ),
            },
        ],
        "education": [
            {
                "degree": "B.Tech, Computer Science",
                "institution": "Jawaharlal Nehru Technological University, Hyderabad",
                "period": "2011 – 2015",
            },
        ],
        "certifications": [
            "Angular — Complete Guide (Maximilian Schwarzmüller, Udemy)",
            "RxJS — Reactive Angular with NgRx (Udemy)",
            "AWS Certified Solutions Architect — Associate",
            "WCAG 2.1 Accessibility Specialist — Deque University",
        ],
    },
]


# ── data: 3 UX/UI Designers ────────────────────────────────────────────

UX_DESIGNERS = [
    {
        "filename": "Neha-Kapoor-UXUI-Designer-SaaS.pdf",
        "name": "Neha Kapoor",
        "role": "Senior Product Designer (SaaS & Web)",
        "profile": (
            "Senior Product Designer with 6+ years specialising in B2B SaaS dashboards, data-heavy "
            "web products, and enterprise design systems. End-to-end ownership from generative "
            "research and information architecture through high-fidelity prototyping and "
            "engineering hand-off. Comfortable driving design strategy, facilitating stakeholder "
            "workshops, and scaling design-system thinking across engineering and product teams."
        ),
        "skills": [
            ("Design", "Figma, Adobe XD, Sketch, Framer, Tokens Studio, Figma Variables"),
            ("Research", "User interviews, usability testing, journey mapping, card sorting, diary studies"),
            ("Prototyping", "Figma Prototypes, ProtoPie, Principle, Framer (interactive)"),
            ("Design Ops", "Storybook, Zeplin, Figma Dev Mode, design tokens, Chromatic"),
            ("Analytics", "Mixpanel, FullStory, Hotjar, Amplitude, Maze"),
            ("Web Basics", "HTML, CSS, responsive grids, WCAG 2.1 accessibility"),
        ],
        "experience": [
            {
                "title": "Principal Product Designer",
                "employer": "B2B SaaS Platform (Confidential)",
                "period": "09/2021 – Present",
                "bullets": [
                    "Owned end-to-end design for a workflow automation product growing from 60 to 500+ enterprise customers; sole designer for the first 18 months, then grew the team to 3.",
                    "Led a full design system overhaul — migrated 120+ components to Figma Variables and Tokens Studio; reduced design inconsistency bugs reported by engineering by 74%.",
                    "Ran 50+ user interviews and 8 moderated usability studies; reframed the onboarding flow which improved 30-day activation from 31% to 58%.",
                    "Designed a no-code workflow builder canvas — evaluated 6 mental models via concept testing before finalising a node-graph interaction that tested 89% task success.",
                    "Partnered with frontend leads to establish a Storybook-driven design-to-code pipeline cutting design-to-production cycle from 3 weeks to 6 days.",
                    "Facilitated quarterly product discovery workshops with C-suite and customer advisory board; contributed to a 2-year product roadmap.",
                ],
            },
            {
                "title": "Senior UX/UI Designer",
                "employer": "Product Design Agency (Confidential)",
                "period": "03/2019 – 08/2021",
                "bullets": [
                    "Designed 18+ SaaS dashboards across HR-Tech, Logistics, Supply Chain, and FinTech verticals for global clients.",
                    "Developed scalable data-heavy component patterns — filterable tables, multi-axis charts, inline editing — with usability-tested interaction models.",
                    "Standardised agency's design delivery process: research synthesis templates, Figma file structure guide, and component naming conventions.",
                    "Mentored 2 mid-level designers and contributed to the agency's internal knowledge-sharing sessions.",
                ],
            },
            {
                "title": "UX Designer",
                "employer": "FinTech Startup",
                "period": "06/2017 – 02/2019",
                "bullets": [
                    "Designed core product flows for a personal finance management app — budgeting, spending insights, and investment tracking — from 0 to 80k users.",
                    "Conducted weekly usability testing; iterated on navigation architecture that reduced task completion time by 37%.",
                    "Created motion design specs for micro-interactions (Principle) handed off to iOS and Android developers.",
                ],
            },
        ],
        "projects": [
            {
                "name": "Workflow Automation Studio",
                "stack": "Figma, Tokens Studio, ProtoPie, Storybook",
                "description": (
                    "Visual workflow builder with drag-and-drop nodes, conditional branching, nested loops, "
                    "version history, and inline AI suggestions. Validated through 6 rounds of concept testing."
                ),
            },
            {
                "name": "SaaS Design System v3",
                "stack": "Figma Variables, Tokens Studio, Storybook, Chromatic, Documentation Site",
                "description": (
                    "Themable design system with 120+ components, semantic colour and spacing tokens, "
                    "dark-mode support, automated visual regression, and a publicly hosted documentation site."
                ),
            },
            {
                "name": "Logistics Ops Dashboard",
                "stack": "Figma, Maze, FullStory, Google Maps API",
                "description": (
                    "Real-time fleet management dashboard for dispatchers managing 500+ vehicles; "
                    "usability-tested with 15 dispatchers, reduced average task completion time by 43%."
                ),
            },
            {
                "name": "HR-Tech Self-Service Portal",
                "stack": "Figma, FigJam, ProtoPie",
                "description": (
                    "Employee self-service portal covering payslips, leave management, benefits selection, "
                    "and performance reviews for a 20,000-person enterprise client."
                ),
            },
            {
                "name": "Personal Finance App (0→80k users)",
                "stack": "Figma, Sketch, Principle",
                "description": (
                    "End-to-end product design for a budgeting and investment-tracking app — "
                    "transaction categorisation, spending insights, goal tracking, and financial health score."
                ),
            },
        ],
        "education": [
            {
                "degree": "Bachelor of Design (Visual Communication)",
                "institution": "National Institute of Design (NID), Ahmedabad",
                "period": "2013 – 2017",
            },
        ],
        "certifications": [
            "Google UX Design Professional Certificate — Coursera",
            "Interaction Design Foundation — Professional Membership",
            "Figma Advanced — Figma Academy",
            "Design Systems — Smashing Magazine Workshop",
        ],
    },
    {
        "filename": "Karan-Patel-UXUI-Designer-Mobile.pdf",
        "name": "Karan Patel",
        "role": "Senior UX / UI Designer (Mobile-First)",
        "profile": (
            "Senior Mobile UX/UI Designer with 7 years designing native iOS and Android experiences "
            "for consumer apps across FinTech, HealthTech, and Travel domains. Expert in iOS HIG, "
            "Material Design 3, micro-interaction design, and Lottie motion systems. Proven ability "
            "to own full product design cycles — from user research and journey mapping through "
            "prototyping, A/B testing, and developer hand-off — while managing relationships with "
            "product managers, engineering leads, and marketing stakeholders."
        ),
        "skills": [
            ("Design", "Figma, Sketch, Adobe XD, Adobe Illustrator, Adobe Photoshop"),
            ("Motion", "Lottie, After Effects, Principle, ProtoPie, Rive"),
            ("Mobile UX", "iOS HIG, Material Design 3, gestural navigation, dark mode, accessibility"),
            ("Research", "Remote usability tests, A/B test design, analytics review, tree testing"),
            ("Analytics", "Firebase Analytics, Mixpanel, Amplitude, AppsFlyer, Hotjar"),
            ("Hand-off", "Figma Dev Mode, Zeplin, asset slicing for iOS/Android, SwiftUI previews"),
        ],
        "experience": [
            {
                "title": "Lead Mobile UX Designer",
                "employer": "Consumer FinTech App (Confidential)",
                "period": "02/2021 – Present",
                "bullets": [
                    "Designed end-to-end mobile journeys for a neo-banking app growing from 800k to 4.2M+ downloads; owned the full design cycle across iOS and Android.",
                    "Led a complete onboarding and KYC redesign — reduced first-transaction time by 48% and drop-off at identity verification by 31%.",
                    "Created a comprehensive Lottie-based motion system (60+ animations) documented in Figma; reduced ad-hoc animation requests to engineering by 80%.",
                    "Ran 30+ remote usability tests and 12 A/B tests via Firebase; contributed to a 22% lift in monthly active engagement.",
                    "Built and maintained platform-specific spec files (SwiftUI previews + Compose annotations) ensuring pixel-perfect implementation across both platforms.",
                    "Mentored 2 junior designers and facilitated biweekly design critique sessions for the mobile design team.",
                ],
            },
            {
                "title": "Senior Mobile UX/UI Designer",
                "employer": "Mobile App Studio (Confidential)",
                "period": "04/2018 – 01/2021",
                "bullets": [
                    "Delivered end-to-end UX/UI for 20+ consumer mobile apps spanning fitness, travel, e-commerce, and EdTech verticals.",
                    "Built a reusable mobile design kit (iOS + Android variants) in Figma used by all 6 designers in the studio.",
                    "Developed and documented a motion design guideline and Lottie asset pipeline that standardised animation quality across client deliveries.",
                    "Translated user research insights into prioritised design backlogs with PMs; reduced average sprint re-work from 3 tickets to 0.8.",
                ],
            },
            {
                "title": "UX Designer",
                "employer": "Travel-Tech Startup",
                "period": "08/2016 – 03/2018",
                "bullets": [
                    "Designed the iOS and Android booking flows for a flight and hotel aggregator app, achieving 4.5★ App Store rating at launch.",
                    "Conducted contextual inquiry research with 25 frequent travellers; findings informed a search UX redesign that improved conversion by 26%.",
                    "Introduced skeleton screens and offline-friendly states, improving perceived performance on low-bandwidth networks.",
                ],
            },
        ],
        "projects": [
            {
                "name": "Neo-Banking App (4.2M downloads)",
                "stack": "Figma, ProtoPie, Lottie, Firebase A/B Testing",
                "description": (
                    "Full visual and interaction design for a neo-banking app covering onboarding/KYC, "
                    "payments, investments, FD/RD, cards management, and rewards. Motion system "
                    "with 60+ Lottie animations."
                ),
            },
            {
                "name": "Fitness & Wellness Tracker",
                "stack": "Figma, Material Design 3, iOS HIG, Lottie, Rive",
                "description": (
                    "Cross-platform fitness app with adaptive training plans, wearable sync, sleep "
                    "insights, and gamified streaks. Custom watchOS and Wear OS companion screens."
                ),
            },
            {
                "name": "Travel Booking App (Multi-modal)",
                "stack": "Sketch, Principle, Figma, Lottie",
                "description": (
                    "Multi-modal booking flow covering flights, hotels, buses, and cabs — optimised for "
                    "low-bandwidth markets with skeleton screens and offline-friendly states."
                ),
            },
            {
                "name": "Mobile Design Kit (iOS + Android)",
                "stack": "Figma, Material Design 3, iOS HIG, Tokens Studio",
                "description": (
                    "Comprehensive mobile design kit with 200+ components, platform-specific variants, "
                    "dark-mode tokens, and a Lottie animation library used across the studio's 20+ projects."
                ),
            },
            {
                "name": "HealthTech Patient App",
                "stack": "Figma, ProtoPie, Lottie, Firebase Analytics",
                "description": (
                    "Patient-facing app for an outpatient clinic network — appointment booking, "
                    "teleconsultation, prescription management, lab results, and health-history timeline."
                ),
            },
        ],
        "education": [
            {
                "degree": "B.Des, Interaction Design",
                "institution": "Symbiosis Institute of Design, Pune",
                "period": "2012 – 2016",
            },
        ],
        "certifications": [
            "Mobile UX Design — Interaction Design Foundation",
            "Motion Design for UI — Coursera",
            "Figma Advanced Prototyping — Figma Academy",
            "iOS Human Interface Guidelines — Apple Developer Certification",
        ],
    },
    {
        "filename": "Ananya-Singh-UXUI-Designer-Product.pdf",
        "name": "Ananya Singh",
        "role": "Lead Product Designer (Research & Strategy)",
        "profile": (
            "Lead Product Designer with 8 years of experience spanning research, interaction design, "
            "systems thinking, and design strategy. Comfortable leading full discovery-to-delivery "
            "cycles across consumer and enterprise products on web, iOS, and Android. Deep expertise "
            "in generative research methodologies, service design, and cross-functional facilitation. "
            "Track record of building and scaling design teams, establishing design operations, and "
            "translating complex domain problems into intuitive, validated product experiences."
        ),
        "skills": [
            ("Design", "Figma, Framer, Sketch, Adobe Creative Cloud, Webflow"),
            ("Research", "Generative interviews, diary studies, contextual inquiry, surveys, tree testing, RITE"),
            ("Strategy", "Service blueprinting, JTBD framework, opportunity solution trees, Jobs mapping"),
            ("Facilitation", "Design sprints, discovery workshops, assumption mapping, How-Might-We sessions"),
            ("Prototyping", "Figma Prototypes, Framer (code components), Lottie, Webflow (live prototypes)"),
            ("Design Ops", "Miro, Notion, FigJam, Loom, Linear, Dovetail, Confluence"),
        ],
        "experience": [
            {
                "title": "Lead Product Designer",
                "employer": "EdTech Platform (Confidential)",
                "period": "05/2021 – Present",
                "bullets": [
                    "Led design for a K-12 adaptive learning product reaching 1.2M students across web and Android tablet; managed a team of 3 designers.",
                    "Ran a 6-week discovery sprint with 35 students, parents, and teachers across 4 Indian states; synthesised findings into a refreshed product vision adopted by the executive team.",
                    "Designed an adaptive assessment system with AI-driven question branching, real-time progress visualisation, and teacher analytics — contributed to a 44% improvement in test completion rates.",
                    "Established design operations: weekly critique rituals, Figma file governance, shared component library with 90+ tokens, and a bi-weekly design–engineering sync.",
                    "Partnered with the ML team to design explainable AI features — surfacing model recommendations in teacher dashboards with confidence indicators and rationale tooltips.",
                    "Facilitated quarterly product strategy workshops with founders and investors; owned the design narrative in 3 Series B fundraising decks.",
                ],
            },
            {
                "title": "Senior UX Designer",
                "employer": "Enterprise SaaS Company (Confidential)",
                "period": "06/2018 – 04/2021",
                "bullets": [
                    "Designed admin, analytics, and automation modules for an enterprise CRM serving 500+ tenants globally.",
                    "Ran comparative usability studies across 8 industry segments; delivered a segment-specific navigation taxonomy that reduced support tickets by 33%.",
                    "Authored a 60-page design system documentation site (Notion + Storybook) adopted by 15 engineers and 4 PMs as the single source of truth.",
                    "Championed accessibility — conducted 12 screen-reader audits; co-wrote an internal accessibility checklist now used in every design review.",
                ],
            },
            {
                "title": "UX / Product Designer",
                "employer": "Digital Product Consultancy",
                "period": "07/2015 – 05/2018",
                "bullets": [
                    "Delivered end-to-end UX/UI for 14 digital products across FinTech, Insurance, Retail, and Government sectors.",
                    "Pioneered service design practice at the consultancy: introduced service blueprinting and journey mapping as standard deliverables on complex projects.",
                    "Facilitated 20+ client discovery workshops and design sprints; built a reusable facilitation toolkit adopted firm-wide.",
                ],
            },
        ],
        "projects": [
            {
                "name": "Adaptive K-12 Learning Platform (1.2M students)",
                "stack": "Figma, Framer, FigJam, Miro, Dovetail",
                "description": (
                    "Discovery-led redesign for student, parent, and teacher personas. AI-driven adaptive "
                    "assessment, gamified learning loops, offline mode, and a real-time teacher analytics "
                    "dashboard. Reduced test abandonment by 44%."
                ),
            },
            {
                "name": "Enterprise CRM — Analytics & Automation",
                "stack": "Figma, Sketch, Tableau (research), FullStory",
                "description": (
                    "Self-serve reporting workspace with drag-and-drop chart builder, shareable dashboards, "
                    "scheduled report delivery, and a no-code workflow automation builder for CRM events."
                ),
            },
            {
                "name": "Healthcare Service Blueprint",
                "stack": "Miro, Figma, Notion, FigJam",
                "description": (
                    "End-to-end service blueprint mapping 16 touchpoints across patient, provider, and "
                    "admin journeys for a 22-clinic outpatient network; informed a ₹8 Cr digital "
                    "transformation roadmap."
                ),
            },
            {
                "name": "Government Citizen Services Portal",
                "stack": "Figma, Framer, Webflow, Dovetail",
                "description": (
                    "Accessible (WCAG 2.1 AA) multilingual portal for 6 state-level citizen services — "
                    "permit applications, grievance redressal, and benefits tracking. Designed for "
                    "low-literacy users with iconographic navigation and audio cues."
                ),
            },
            {
                "name": "InsurTech Quote & Policy Platform",
                "stack": "Figma, ProtoPie, Maze, Hotjar",
                "description": (
                    "End-to-end redesign of a commercial insurance quote-to-bind flow — reduced quote "
                    "completion time from 22 to 8 minutes; validated via 3 rounds of moderated usability testing."
                ),
            },
        ],
        "education": [
            {
                "degree": "M.Des, Human-Computer Interaction",
                "institution": "Industrial Design Centre, IIT Bombay",
                "period": "2013 – 2015",
            },
            {
                "degree": "B.Tech, Computer Engineering",
                "institution": "Mumbai University",
                "period": "2009 – 2013",
            },
        ],
        "certifications": [
            "Service Design — Interaction Design Foundation",
            "User Research Bootcamp — UX Design Institute",
            "Design Sprint Facilitator — Google Ventures (GV)",
            "Accessibility Specialist — Deque University (CPACC)",
        ],
    },
]


def main():
    for cv in FRONTEND_DEVS + UX_DESIGNERS:
        out = OUT_DIR / cv["filename"]
        render_cv(cv, out)
        print(f"  ✓ {out.relative_to(ROOT)}")
    print(f"\nGenerated {len(FRONTEND_DEVS) + len(UX_DESIGNERS)} CVs in {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
