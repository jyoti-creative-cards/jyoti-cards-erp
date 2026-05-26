export type Service = {
  id: string;
  title: string;
  summary: string;
  tags: string[];
  overview: string;
  highlights: string[];
  roles: string[];
};

export const services: Service[] = [
  {
    id: "frontend",
    title: "Frontend Developer Staffing",
    summary:
      "UI engineers for React, Angular, Vue, and Next.js — pixel-perfect, performant, production-ready.",
    tags: ["React", "Next.js", "Angular", "TypeScript"],
    overview:
      "We place senior and mid-level frontend developers who integrate directly into your design and engineering workflows — from component libraries to full product rebuilds.",
    highlights: [
      "Responsive web & SPA development",
      "Design system & component architecture",
      "Performance optimization & accessibility",
      "Code reviews and frontend best practices",
    ],
    roles: [
      "Senior React Developer",
      "Next.js Engineer",
      "Angular Developer",
      "UI / UX Engineer",
    ],
  },
  {
    id: "ai",
    title: "AI & ML Engineer Staffing",
    summary:
      "ML engineers, LLM integrators, and data scientists to embed AI into your products.",
    tags: ["Python", "TensorFlow", "PyTorch", "LLMs"],
    overview:
      "From model training to production inference pipelines, our AI engineers help you ship intelligent features — chatbots, recommendation engines, computer vision, and more.",
    highlights: [
      "LLM integration & prompt engineering",
      "Custom model training & fine-tuning",
      "MLOps & deployment pipelines",
      "NLP, computer vision & predictive analytics",
    ],
    roles: [
      "ML Engineer",
      "AI Integration Specialist",
      "Data Scientist",
      "MLOps Engineer",
    ],
  },
  {
    id: "web",
    title: "Web App Development",
    summary:
      "Full-stack web teams for MERN, MEAN, and enterprise SaaS — scoped, staffed, and delivered.",
    tags: ["MERN", "Node.js", "MongoDB", "GraphQL"],
    overview:
      "We assemble complete web development squads or augment your existing backend team with frontend and full-stack engineers for portals, dashboards, and SaaS platforms.",
    highlights: [
      "MERN & MEAN stack development",
      "REST & GraphQL API integration",
      "Enterprise portals & admin dashboards",
      "QA, deployment & post-launch support",
    ],
    roles: [
      "Full-Stack Developer",
      "Node.js Backend Engineer",
      "MERN Stack Developer",
      "Technical Lead",
    ],
  },
  {
    id: "mobile",
    title: "Mobile App Development",
    summary:
      "iOS, Android, and cross-platform teams — from MVP to App Store launch.",
    tags: ["React Native", "Flutter", "Swift", "Kotlin"],
    overview:
      "Native and cross-platform mobile developers who ship polished apps for both iOS and Android, with experience in push notifications, offline sync, and store submissions.",
    highlights: [
      "Native iOS (Swift) & Android (Kotlin)",
      "Cross-platform with React Native & Flutter",
      "App Store & Play Store deployment",
      "Push notifications, analytics & offline support",
    ],
    roles: [
      "React Native Developer",
      "Flutter Engineer",
      "iOS Developer",
      "Android Developer",
    ],
  },
  {
    id: "teams",
    title: "Dedicated Product Teams",
    summary:
      "Fully managed squads aligned to your roadmap — frontend, backend, and AI combined.",
    tags: ["Agile", "Scrum", "CI/CD", "DevOps"],
    overview:
      "Get a dedicated pod of engineers — tech lead, developers, and QA — that works exclusively on your product with weekly demos and transparent reporting.",
    highlights: [
      "Dedicated squad with tech lead",
      "Agile sprints with weekly demos",
      "CI/CD pipeline setup & maintenance",
      "Flexible scaling up or down",
    ],
    roles: [
      "Tech Lead",
      "Scrum-aligned Developer Pod",
      "QA Engineer",
      "DevOps Specialist",
    ],
  },
  {
    id: "delivery",
    title: "End-to-End Software Delivery",
    summary:
      "Discovery through deployment — we staff, build, and manage the full lifecycle.",
    tags: ["AWS", "Docker", "Kubernetes", "Microservices"],
    overview:
      "For companies that need a complete delivery partner: we handle discovery, architecture, development, testing, cloud deployment, and ongoing maintenance.",
    highlights: [
      "Requirements & architecture planning",
      "Cloud deployment (AWS, Azure)",
      "Containerization & microservices",
      "SLA-backed maintenance & support",
    ],
    roles: [
      "Solution Architect",
      "Cloud Engineer",
      "Full-Stack Team",
      "Project Manager",
    ],
  },
];

export type TechItem = {
  name: string;
  icon: string;
  color?: string;
};

export type TechCategory = {
  id: string;
  label: string;
  items: TechItem[];
};

export const techCategories: TechCategory[] = [
  {
    id: "frontend",
    label: "Frontend",
    items: [
      { name: "React", icon: "react", color: "61DAFB" },
      { name: "Next.js", icon: "nextdotjs", color: "FFFFFF" },
      { name: "Angular", icon: "angular", color: "DD0031" },
      { name: "Vue.js", icon: "vuedotjs", color: "4FC08D" },
      { name: "TypeScript", icon: "typescript", color: "3178C6" },
      { name: "JavaScript", icon: "javascript", color: "F7DF1E" },
      { name: "HTML5", icon: "html5", color: "E34F26" },
      { name: "CSS3", icon: "css3", color: "1572B6" },
      { name: "Tailwind", icon: "tailwindcss", color: "06B6D4" },
      { name: "Redux", icon: "redux", color: "764ABC" },
      { name: "Vite", icon: "vite", color: "646CFF" },
      { name: "Sass", icon: "sass", color: "CC6699" },
    ],
  },
  {
    id: "ai",
    label: "AI & ML",
    items: [
      { name: "Python", icon: "python", color: "3776AB" },
      { name: "TensorFlow", icon: "tensorflow", color: "FF6F00" },
      { name: "PyTorch", icon: "pytorch", color: "EE4C2C" },
      { name: "OpenAI", icon: "openai", color: "FFFFFF" },
      { name: "Hugging Face", icon: "huggingface", color: "FFD21E" },
      { name: "Jupyter", icon: "jupyter", color: "F37626" },
      { name: "Docker", icon: "docker", color: "2496ED" },
      { name: "Kubernetes", icon: "kubernetes", color: "326CE5" },
      { name: "Pandas", icon: "pandas", color: "150458" },
      { name: "NumPy", icon: "numpy", color: "013243" },
    ],
  },
  {
    id: "mobile",
    label: "Mobile",
    items: [
      { name: "React Native", icon: "react", color: "61DAFB" },
      { name: "Flutter", icon: "flutter", color: "02569B" },
      { name: "Swift", icon: "swift", color: "F05138" },
      { name: "Kotlin", icon: "kotlin", color: "7F52FF" },
      { name: "Android", icon: "android", color: "3DDC84" },
      { name: "Apple", icon: "apple", color: "FFFFFF" },
      { name: "Expo", icon: "expo", color: "FFFFFF" },
      { name: "Firebase", icon: "firebase", color: "DD2C00" },
    ],
  },
  {
    id: "backend",
    label: "Backend & Cloud",
    items: [
      { name: "Node.js", icon: "nodedotjs", color: "339933" },
      { name: "Express", icon: "express", color: "FFFFFF" },
      { name: "MongoDB", icon: "mongodb", color: "47A248" },
      { name: "PostgreSQL", icon: "postgresql", color: "4169E1" },
      { name: "MySQL", icon: "mysql", color: "4479A1" },
      { name: "GraphQL", icon: "graphql", color: "E10098" },
      { name: "Redis", icon: "redis", color: "FF4438" },
      { name: "AWS", icon: "amazonaws", color: "FF9900" },
      { name: "Docker", icon: "docker", color: "2496ED" },
      { name: "Kubernetes", icon: "kubernetes", color: "326CE5" },
    ],
  },
];

export const clients = [
  { name: "Chandrawat Concrete Works", logo: "/clients/client-concrete.png" },
  { name: "Firangi Cafe & Bar", logo: "/clients/client-firangi.png" },
  { name: "The Grand Shaurya", logo: "/clients/client-grand-shaurya.png" },
  { name: "Techturtle", logo: "/clients/client-techturtle.png" },
  { name: "SIG SIGMA", logo: "/clients/client-sig-sigma.png" },
  { name: "Tripolic", logo: "/clients/client-tripolic.jpeg" },
  { name: "Jyoti Creative Cards", logo: "/clients/client-jyoti.jpeg" },
];

export const stats = [
  { value: "50+", label: "Developers Placed" },
  { value: "10+", label: "Enterprise Clients" },
  { value: "100%", label: "Client Retention" },
  { value: "2 Weeks", label: "Avg. Time to Hire" },
];

export const processSteps = [
  { step: "01", title: "Discovery", description: "Stack, gaps & timeline." },
  { step: "02", title: "Match", description: "Pre-vetted candidates." },
  { step: "03", title: "Onboard", description: "Integrated in days." },
  { step: "04", title: "Support", description: "Ongoing oversight." },
];
