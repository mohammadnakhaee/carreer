// CV generator for the 2026-07-09 pipeline batch (reports #161-165, #170).
// Reads the rendered base CV and swaps Professional Summary + Core Competencies per company.
import { readFile, writeFile } from 'fs/promises';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');
const base = await readFile(resolve(root, 'output/cv-amir-golparvar-owkin-2026-07-06.html'), 'utf8');

const date = '2026-07-09';

const companies = {
  'bees-bears': {
    summary: `Berlin-based full-stack developer with 6+ years shipping production Python (FastAPI) and React features end-to-end. At FAIRmat/HU Berlin I own the full stack from database schema and API design to a React GUI used by 600+ researchers, deploying to AWS with Docker. I work autonomously, make architecture decisions, and lead complex projects from concept to production. I also build AI-powered features, including NOMAD Compass, a production RAG assistant, matching your push to ship AI-powered financing tools fast. Portfolio: amirgolp.github.io`,
    tags: ['Python / FastAPI', 'React', 'AWS', 'Docker', 'End-to-end ownership', 'AI-powered features', 'Architecture decisions', 'Autonomous delivery'],
  },
  'cito': {
    summary: `Berlin-based engineer with 6+ years building production Python systems and hands-on LLM deployment experience. At FAIRmat/HU Berlin I architected NOMAD Compass, a production RAG assistant over docs, schemas, and code, and I own the FastAPI services and distributed workers (Celery/Temporal) behind a platform of 19M+ entries. I design reliable pipelines, add observability and testing (pytest, pytest-bdd), and take AI features from proof-of-concept to production. Strong on API and system design for AI-agent workloads. Portfolio: amirgolp.github.io`,
    tags: ['Python', 'LLM / RAG (production)', 'AI-agent systems', 'FastAPI', 'Observability & evals', 'Distributed workers', 'Reliability', 'System design'],
  },
  'liveeo-freelance': {
    summary: `Berlin-based full-stack engineer with 6+ years shipping production features end-to-end, from PostgreSQL schema through APIs to React + TypeScript UIs. At FAIRmat/HU Berlin I build backend services in Python (FastAPI) and Node.js/Express and own the React GUI for 600+ users, deployed to AWS with GitLab CI/CD. I work daily in an LLM-integrated, agentic-coding setup and handle large scientific and spatial datasets. I ramp fast, own features from exploration to continuous deployment, and deliver as a self-directed contractor. Portfolio: amirgolp.github.io`,
    tags: ['React / TypeScript', 'Node.js', 'Python', 'PostgreSQL', 'AWS', 'GitLab CI/CD', 'Agentic coding', 'End-to-end delivery'],
  },
  'sumup-sidekick': {
    summary: `Berlin-based full-stack engineer with 6+ years shipping production web apps end-to-end in React and TypeScript on the front end and REST/microservices on the back end. At FAIRmat/HU Berlin I own features from database and API design to a React GUI (Vite, MUI, TanStack Query) for 600+ users, and I run these services on Kubernetes + Helm across AWS. I take genuine ownership from scoping through production, work closely with stakeholders, and raise engineering standards through TDD/BDD and CI/CD. Portfolio: amirgolp.github.io`,
    tags: ['React / TypeScript', 'REST & microservices', 'Kubernetes / Helm', 'TanStack Query', 'End-to-end ownership', 'TDD/BDD', 'CI/CD', 'Stakeholder collaboration'],
  },
  'enpal': {
    summary: `Berlin-based full-stack engineer with 6+ years shipping production features end-to-end across a 50/50 front-end and back-end split. At FAIRmat/HU Berlin I own the React + TypeScript GUI for 600+ users and build the backend services, APIs, and PostgreSQL data models behind them, deployed to AWS. I design scalable APIs, use AI tooling to move fast, and hold high engineering standards through automated testing and CI/CD. Comfortable owning end-to-end feature delivery in a product-focused team. Portfolio: amirgolp.github.io`,
    tags: ['React / TypeScript', 'Node.js', 'PostgreSQL', 'AWS', 'API design', 'End-to-end ownership', 'AI tooling', 'Automated testing'],
  },
  'overfly': {
    summary: `Berlin-based full-stack engineer with 6+ years shipping production software end-to-end and hands-on applied-AI experience. At FAIRmat/HU Berlin I architected NOMAD Compass, a production RAG assistant, and I own features in React + TypeScript and Node with PostgreSQL, deployed to cloud. I lead projects from concept to production-ready apps, choose the stack, integrate LLM tooling (RAG, OpenAI-style APIs), and work directly with the people who use what I build. I move fast, own outcomes, and thrive with autonomy. Portfolio: amirgolp.github.io`,
    tags: ['React / TypeScript', 'Node.js', 'LLM / RAG integration', 'PostgreSQL', 'Cloud deploy', 'End-to-end ownership', 'Client-facing', 'Ships fast'],
  },
};

const summaryRe = /(<div class="summary-text">)[\s\S]*?(<\/div>)/;
const compRe = /(<div class="competencies-grid">)[\s\S]*?(<\/div>)/;

for (const [slug, cfg] of Object.entries(companies)) {
  const tagsHtml = cfg.tags.map(t => `\n      <span class="competency-tag">${t}</span>`).join('') + '\n    ';
  let html = base
    .replace(summaryRe, `$1${cfg.summary}$2`)
    .replace(compRe, `$1${tagsHtml}$2`);
  const out = resolve(root, `output/cv-amir-golparvar-${slug}-${date}.html`);
  await writeFile(out, html, 'utf8');
  console.log('wrote', out);
}
