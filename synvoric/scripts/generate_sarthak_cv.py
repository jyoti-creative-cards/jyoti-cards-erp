#!/usr/bin/env python3
"""Generate Sarthak Shukla CV in the standard Synvoric CV template."""

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

    # Awards
    if data.get("awards"):
        y = maybe_new_page(y, 80)
        y = draw_section(c, y, "Awards")
        for award in data["awards"]:
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(NAVY)
            c.drawString(ML, y, award["title"])
            c.setFont("Helvetica", 9)
            c.setFillColor(SLATE)
            c.drawRightString(ML + CW, y, award["period"])
            y -= 12
            c.setFont("Helvetica-Oblique", 9)
            c.setFillColor(SLATE)
            c.drawString(ML + 10, y, award["org"])
            y -= 12
            y = draw_text(c, ML + 10, y, award["description"], size=9, max_width=CW - 10)
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


SARTHAK_CV = {
    "filename": "Sarthak-Shukla-Frontend-Developer.pdf",
    "name": "Sarthak Shukla",
    "role": "Senior Frontend Developer (React & React Native)",
    "profile": (
        "Senior Frontend Developer with 6 years of experience building scalable, high-performance "
        "web and mobile applications across AI/ML, e-commerce, and SaaS domains. Expert in "
        "translating complex Figma designs into production-grade React.js and React Native "
        "interfaces. Deep proficiency in state management, REST APIs, GenAI integrations, and "
        "performance optimisation. Proven track record of owning full product cycles — from "
        "Figma handoff through deployment — and delivering measurable improvements in user "
        "experience and business metrics."
    ),
    "skills": [
        ("Frontend", "React.js, Next.js, JavaScript (ES2022+), TypeScript, HTML5, CSS3, Tailwind CSS"),
        ("Mobile", "React Native, Expo, Redux Toolkit, Context API, React Navigation"),
        ("GenAI / ML", "OpenAI API, vector search, LangChain, Python (ML pipelines)"),
        ("Backend / APIs", "REST APIs, Node.js (basic), FastAPI, WebSockets"),
        ("Design", "Figma (design handoff, prototyping), responsive grid systems"),
        ("Tooling", "Git, GitHub, GitHub Actions, Sentry, Vercel, AWS S3"),
    ],
    "experience": [
        {
            "title": "Senior Frontend Developer",
            "employer": "Shilsha Technologies",
            "period": "04/2021 – 02/2026",
            "bullets": [
                "Key Driver Analytics AI Platform: Architected the full React.js frontend for an AI/ML safety analytics product — complex data visualisations, real-time model outputs, and configurable alert dashboards; reduced analyst report generation time by 60%.",
                "Customer Commerce Mobile App (React Native): Led end-to-end mobile development from Figma mockups — multi-vendor product catalogue, cart, order tracking, Razorpay/UPI payment flows, and push notifications via FCM; shipped to Play Store with 4.6★ rating.",
                "Seller Commerce Dashboard (React.js): Built a full-featured seller portal with inventory management, order fulfilment, sales analytics, performance scorecards, and bulk operations — onboarded 800+ sellers at launch.",
                "GenAI Document Assistant: Developed a React.js + FastAPI GenAI app allowing users to upload PDFs and query documents in natural language using OpenAI API and FAISS vector search; reduced manual document review time by 70% for enterprise users.",
                "Customer Behaviour Prediction AI App: Built the frontend for an ML churn-prediction platform — feature input forms, model confidence visualisations, cohort comparison charts, and exportable reports; directly contributed to a 22% reduction in customer churn for a pilot client.",
                "Established a shared component library and Figma-to-code design token pipeline used across all 5 product teams, cutting new-feature UI build time by 40%.",
                "Mentored 2 junior frontend developers; conducted weekly code reviews and pair-programming sessions.",
            ],
        },
        {
            "title": "Frontend Developer",
            "employer": "Fodrix",
            "period": "02/2020 – 03/2021",
            "bullets": [
                "Built and published a reusable JavaScript utility library that standardised cross-project functionality — adopted across 8 internal projects, saving an estimated 3 dev-weeks per quarter.",
                "Implemented Multi-Factor Authentication (MFA) with Google Authenticator and TOTP, hardening security for a B2B SaaS platform with 5k+ business users.",
                "Developed the customer management module in the Loop Dashboard using React and Redux — user profiles, segmentation filters, activity timelines, and bulk messaging UI.",
                "Built a React-based Shopify storefront POC integrating headless commerce APIs with a custom checkout and product configurator.",
                "Enhanced overall UX rating from 55% to 85% (internal NPS benchmarks) through Figma-led redesigns executed in React.js and React Native.",
                "Contributed to website development using React.js and Context API; improved Lighthouse performance score from 54 to 88.",
            ],
        },
        {
            "title": "Junior Frontend Developer",
            "employer": "Freelance / Contract",
            "period": "06/2018 – 01/2020",
            "bullets": [
                "Delivered 6 client websites and web apps using React.js, HTML5, CSS3, and vanilla JavaScript — sectors included education, retail, and local services.",
                "Built a school management portal with student attendance tracking, fee management, and parent notification system.",
                "Developed responsive landing pages and marketing sites achieving sub-2s load times via lazy loading and image optimisation.",
            ],
        },
    ],
    "awards": [
        {
            "title": "Performer of the Year (2023–2024)",
            "org": "Shilsha Technologies",
            "period": "31/03/2024",
            "description": (
                "Recognised for outstanding contributions across 3 concurrent product lines — "
                "AI platform, mobile commerce app, and seller dashboard — delivered on time with "
                "zero critical post-release bugs."
            ),
        },
    ],
    "projects": [
        {
            "name": "Key Driver Analytics AI Platform",
            "stack": "React.js, TypeScript, Recharts, FastAPI, OpenAI API, AWS S3",
            "description": (
                "AI/ML safety analytics dashboard with real-time model outputs, configurable KPI "
                "dashboards, anomaly alerting, and PDF report export. Reduced analyst cycle time by 60%."
            ),
        },
        {
            "name": "Seller Commerce Dashboard",
            "stack": "React.js, Redux Toolkit, Tailwind CSS, REST APIs, Recharts",
            "description": (
                "Full-featured seller portal with inventory management, order fulfilment, sales "
                "analytics, and bulk operations. Onboarded 800+ sellers at launch."
            ),
        },
        {
            "name": "GenAI Document Assistant",
            "stack": "React.js, FastAPI, OpenAI API, FAISS, LangChain, AWS S3",
            "description": (
                "Natural-language document query tool — users upload PDFs and ask questions; "
                "answers grounded via vector search. Reduced manual review time by 70% for enterprise users."
            ),
        },
        {
            "name": "Customer Commerce Mobile App",
            "stack": "React Native, Expo, Redux Toolkit, FCM, Razorpay, REST APIs",
            "description": (
                "Multi-vendor shopping app covering catalogue, cart, order tracking, Razorpay/UPI "
                "checkout, and push notifications. 4.6★ Play Store rating."
            ),
        },
        {
            "name": "Customer Behaviour Prediction Platform",
            "stack": "React.js, Python (ML pipeline), TypeScript, Recharts, FastAPI",
            "description": (
                "Churn prediction frontend — feature inputs, model confidence visualisations, "
                "cohort comparisons, and exportable reports. Pilot client reduced churn by 22%."
            ),
        },
    ],
    "education": [
        {
            "degree": "B.Sc",
            "institution": "Chaudhary Charan Singh University",
            "period": "07/2018 – 08/2021",
        },
        {
            "degree": "Intermediate (Science)",
            "institution": "Meerut Public School, CBSE",
            "period": "04/2017 – 03/2018",
        },
    ],
    "certifications": [
        "MaitY-NASSCOM Full Stack Development (MERN) — Government of India",
        "Frontend Development with React.js — Coding Ninjas",
        "Frontend Web Development — University of Michigan",
        "JavaScript Basics to Advance — Coding Ninjas",
        "Advance Front-End Web Development with React — Full Stack",
        "Data Structure in Python — Coding Ninjas",
        "Introduction to Python — Coding Ninjas",
    ],
}


def main():
    out = OUT_DIR / SARTHAK_CV["filename"]
    render_cv(SARTHAK_CV, out)
    print(f"  ✓ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
