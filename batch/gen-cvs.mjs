// One-off CV generator for the 2026-07-06 pipeline batch.
// Reads the rendered base CV and swaps Professional Summary + Core Competencies per company.
import { readFile, writeFile } from 'fs/promises';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');
const base = await readFile(resolve(root, 'output/cv-amir-golparvar-owkin-2026-07-06.html'), 'utf8');

const date = '2026-07-06';

const companies = {
  'code-compass': {
    summary: `Berlin-based full-stack developer with 6+ years shipping production web apps end-to-end in React + TypeScript on the front end and Node.js/Express and Python/FastAPI on the back end. At FAIRmat/HU Berlin I own features from PostgreSQL/MongoDB schema through REST APIs to a React GUI used by 600+ researchers, deployed with CI/CD (GitHub Actions, GitLab CI) to AWS and Kubernetes. I also architected NOMAD Compass, a production RAG assistant, so I ship AI-enabled products, not just demos. Comfortable owning architecture and setting engineering best practices. Portfolio: amirgolp.github.io`,
    tags: ['React / TypeScript', 'Node.js', 'Python / FastAPI', 'REST APIs', 'PostgreSQL & MongoDB', 'AI / LLM integration', 'CI/CD', 'System design'],
  },
  'zendesk': {
    summary: `Berlin-based engineer with 6+ years shipping production systems end-to-end and hands-on LLM deployment experience. At FAIRmat/HU Berlin I architected NOMAD Compass, a production RAG assistant over docs, schemas, and code, and I build the integrations and data pipelines (FastAPI, Celery/Temporal) behind a platform serving 600+ users across 10+ institutions. I deploy on Docker, Kubernetes + Helm, and AWS, and I resolve escalated reliability and data issues. Fluent in Python and JavaScript/TypeScript, I take solutions from discovery and proof-of-concept to production rollout. Portfolio: amirgolp.github.io`,
    tags: ['RAG (production)', 'LLM deployment', 'Python', 'JavaScript / TypeScript', 'Docker / Kubernetes', 'AWS cloud', 'Integrations & pipelines', 'Solutions delivery'],
  },
  'cresta': {
    summary: `Berlin-based backend engineer with 6+ years building production services and data systems in Python. At FAIRmat/HU Berlin I design and operate FastAPI microservices and distributed workers (Celery/Temporal) over a platform of 19M+ entries and 114 TB+ of data, with Elasticsearch, MongoDB, and PostgreSQL for storage and search. I run these on Kubernetes + Helm across AWS, tune queries and caching for responsive data-dense UIs, and troubleshoot distributed systems in production. Strong on API design, data modeling, and reliability. Portfolio: amirgolp.github.io`,
    tags: ['Python / FastAPI', 'Elasticsearch', 'PostgreSQL', 'Distributed systems', 'Query optimization', 'Kubernetes / Helm', 'REST API design', 'Data modeling'],
  },
  'helsing': {
    summary: `Berlin-based front-end engineer with 6+ years owning production UIs end-to-end in React. At FAIRmat/HU Berlin I build and maintain the GUI for a 600+ researcher community — uploads, faceted search, and data viewers — plus a reusable React component library documented in Storybook. I specialize in turning complex, high-volume data into legible, interactive views (Plotly, custom viewers, micro-CT slice rendering) and integrate REST/GraphQL backends. Polyglot (Python, TypeScript, C++), I navigate unfamiliar codebases comfortably and drive code review and testing (Playwright E2E). Portfolio: amirgolp.github.io`,
    tags: ['React', 'Data visualization', 'Component library', 'TypeScript', 'REST / GraphQL', 'Plotly / custom viewers', 'UI ownership', 'Testing (Playwright)'],
  },
  'pandadoc-embedded': {
    summary: `Berlin-based front-end engineer with 6+ years shipping polished, production React + TypeScript interfaces end-to-end. At FAIRmat/HU Berlin I own the GUI for 600+ users — from concept to production components — and maintain a reusable component library documented in Storybook. I build developer-facing surfaces (FastAPI APIs, MkDocs docs) and work daily in an LLM-integrated codebase, adopting AI tooling to prototype fast. I care about interaction quality, accessibility, and performance across the surfaces I own. Portfolio: amirgolp.github.io`,
    tags: ['React / TypeScript', 'Component systems', 'Modern CSS', 'Developer experience', 'LLM tooling', 'UI ownership', 'Prototyping', 'Storybook'],
  },
  'nomerra': {
    summary: `Berlin-based full-stack engineer with 6+ years shipping production software end-to-end, from PostgreSQL schema through APIs to React (with TanStack Query). At FAIRmat/HU Berlin I architected NOMAD Compass, a production agentic/RAG assistant with context engineering and observability, and I build backend services (FastAPI, Node/Express) plus long-running Temporal/Celery workflows. I move fast, own products end-to-end, and translate user problems into shipped features. Comfortable building 0-to-1 under ambiguity. Portfolio: amirgolp.github.io`,
    tags: ['Full-stack ownership', 'Agentic / RAG', 'React / TanStack', 'Node.js / TypeScript', 'PostgreSQL', 'Observability', 'Ships fast', '0-to-1 building'],
  },
  'pandadoc-growth': {
    summary: `Berlin-based front-end engineer with 6+ years shipping polished, production React + TypeScript interfaces end-to-end. At FAIRmat/HU Berlin I own the GUI for 600+ users, set quality standards through code review and a reusable component library (Storybook), and work daily in an LLM-integrated codebase, using AI tooling to prototype and ship fast. I focus on shipped impact and team velocity, taking ideas from concept to production components. Portfolio: amirgolp.github.io`,
    tags: ['React / TypeScript', 'Component systems', 'Modern CSS', 'LLM tooling', 'UI ownership', 'Developer experience', 'Prototyping', 'Storybook'],
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
