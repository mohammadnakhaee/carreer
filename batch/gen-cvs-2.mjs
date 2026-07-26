// CV generator for the 2026-07-06 pipeline batch (report #126-129).
// Reads the rendered base CV and swaps Professional Summary + Core Competencies per company.
import { readFile, writeFile } from 'fs/promises';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');
const base = await readFile(resolve(root, 'output/cv-amir-golparvar-owkin-2026-07-06.html'), 'utf8');

const date = '2026-07-06';

const companies = {
  'synergeticon': {
    summary: `Berlin-based engineer with 6+ years building production Python systems and hands-on RAG experience. At FAIRmat/HU Berlin I architected NOMAD Compass, a production RAG assistant over docs, schemas, and code, and I build async FastAPI + Pydantic services with Celery/Temporal workers over a platform of 19M+ entries and 114 TB+ of data. I ship with modern Python tooling (pytest, pytest-bdd, TDD) and CI/CD, and deploy on Docker and AWS. I already work daily in an LLM-integrated codebase and adopt agentic tooling quickly. Portfolio: amirgolp.github.io`,
    tags: ['RAG (production)', 'LLM & agent integration', 'Python / async', 'FastAPI / Pydantic', 'pytest / TDD', 'Docker', 'AWS cloud', 'Distributed workers'],
  },
  'priojet': {
    summary: `Berlin-based full-stack developer with 6+ years shipping production web apps end-to-end, from PostgreSQL/MongoDB schema through APIs to React UIs. At FAIRmat/HU Berlin I own features across the whole stack for 600+ users and previously built secure Node.js/Express REST APIs with JWT auth deployed to AWS. Comfortable with GraphQL-style API design, Docker, and CI/CD (GitHub Actions, GitLab CI), I make architecture decisions and ramp fast on new frameworks. I ship features across the stack without handoffs. Portfolio: amirgolp.github.io`,
    tags: ['Full-stack ownership', 'Node.js / TypeScript', 'React', 'PostgreSQL & MongoDB', 'REST / GraphQL', 'Docker', 'CI/CD', 'System design'],
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
