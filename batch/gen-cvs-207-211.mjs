import { readFileSync, writeFileSync } from 'node:fs';

const base = readFileSync('output/cv-amir-golparvar-bees-bears-2026-07-09.html', 'utf8');

const roles = {
  'almedia': {
    summary: `Berlin-based full-stack developer with 6+ years shipping production Python (FastAPI) and Node.js features end-to-end, frontend to database. At FAIRmat/HU Berlin I own the full stack from schema and API design to a React GUI used by 600+ researchers, and I built NOMAD Compass, a production RAG assistant that integrates LLM APIs into internal tooling. I work autonomously, make architecture calls, and translate business needs into shipped software fast, matching your push to build AI-powered internal tools across a 70M-user platform. Portfolio: amirgolp.github.io`,
    tags: ['Python / FastAPI', 'Node.js', 'TypeScript', 'React', 'AI API Integration', 'RAG / LLM', 'Automation Workflows', 'End-to-end ownership'],
  },
  'hivemq': {
    summary: `Berlin-based full-stack developer with 6+ years building production services in TypeScript/React and Python, backed by deep distributed-systems work. At FAIRmat/HU Berlin I operate Kubernetes deployments and event-driven pipelines with RabbitMQ, Kafka, and Temporal, and own a React GUI used by 600+ researchers. I built NOMAD Compass, a production RAG assistant, and drive observable, self-healing infrastructure through CI/CD and TDD/BDD, matching your work architecting autonomous agent systems on AWS. Portfolio: amirgolp.github.io`,
    tags: ['TypeScript', 'React', 'Node.js', 'AWS', 'Distributed Systems', 'LLM Workflows', 'DevOps / Monitoring', 'Idempotent Design'],
  },
  'hawk': {
    summary: `Berlin-based full-stack developer with 6+ years shipping production Python (FastAPI) and React/TypeScript features end-to-end. At FAIRmat/HU Berlin I own the full stack from Postgres schema and API design to a React GUI used by 600+ researchers, deploy on Kubernetes, and orchestrate distributed workflows with Temporal and Celery. I built NOMAD Compass, a production RAG assistant with schema-grounded retrieval and evaluation, matching your work building an agentic Investigation Agent with reliability and observability at its core. Portfolio: amirgolp.github.io`,
    tags: ['Python / FastAPI', 'React / TypeScript', 'Postgres', 'Kubernetes', 'Agentic AI', 'RAG / LLM Evals', 'Agent Orchestration', 'End-to-end ownership'],
  },
  'axel-springer-livestreaming': {
    summary: `Berlin-based full-stack developer with 6+ years building and operating production microservices, from FastAPI services to Kubernetes deployments. At FAIRmat/HU Berlin I run observable, resilient services on Kubernetes and Helm behind nginx, with event-driven processing via RabbitMQ, Kafka, and Temporal, serving a 600+ researcher community. I drive full-lifecycle delivery through CI/CD, TDD/BDD (pytest-bdd, Playwright), and production monitoring, matching your live-streaming microservice ecosystem. Portfolio: amirgolp.github.io`,
    tags: ['Kubernetes / Helm', 'Docker', 'AWS', 'Microservices', 'CI/CD', 'Observability', 'BDD', 'Python'],
  },
};

for (const [slug, cfg] of Object.entries(roles)) {
  const tagHtml = cfg.tags.map(t => `<span class="competency-tag">${t}</span>`).join('\n      ');
  let html = base
    .replace(/(<div class="summary-text">)[\s\S]*?(<\/div>)/, `$1${cfg.summary}$2`)
    .replace(/(<div class="competencies-grid">)[\s\S]*?(<\/div>)/, `$1\n      ${tagHtml}\n    $2`);
  const out = `output/cv-amir-golparvar-${slug}-2026-07-18.html`;
  writeFileSync(out, html);
  console.log('wrote', out);
}
