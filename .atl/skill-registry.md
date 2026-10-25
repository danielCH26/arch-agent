---
type: skill-registry
project: arch-agent
generated: 2026-09-05
source: scanned from orchestrator system prompt <available_skills> block
---

# Skill Registry - arch-agent

Catalogo de skills detectados y disponibles para este proyecto, indexado
por trigger y path. Sub-agents deben resolver skills desde este registro
antes de delegar trabajo, copiando los paths exactos al prompt de cada
delegacion.

## Installer skills (per-user, en `~/.config/opencode/skills/`)

| Skill | Trigger | Path |
| --- | --- | --- |
| _shared | Shared SDD references (no invocable) | `~/.config/opencode/skills/_shared/SKILL.md` |
| branch-pr | Crear PRs con issue-first checks | `~/.config/opencode/skills/branch-pr/SKILL.md` |
| chained-pr | Split oversized changes into stacked PRs (>400 lines) | `~/.config/opencode/skills/chained-pr/SKILL.md` |
| cognitive-doc-design | Design docs that reduce cognitive load | `~/.config/opencode/skills/cognitive-doc-design/SKILL.md` |
| comment-writer | PR feedback, reviews, GitHub comments | `~/.config/opencode/skills/comment-writer/SKILL.md` |
| gentle-ai-bench | Bench / journeys / driven mode | `~/.config/opencode/skills/gentle-ai-bench/SKILL.md` |
| go-testing | Go tests, golden files, Bubbletea teatest | `~/.config/opencode/skills/go-testing/SKILL.md` |
| issue-creation | Crear y triagear GitHub issues | `~/.config/opencode/skills/issue-creation/SKILL.md` |
| judgment-day | Dual review / adversarial review | `~/.config/opencode/skills/judgment-day/SKILL.md` |
| rdd-defect-workflow | RDD defects, review authority, receipts | `~/.config/opencode/skills/rdd-defect-workflow/SKILL.md` |
| sdd-apply | Implement SDD tasks from specs/design | `~/.config/opencode/skills/sdd-apply/SKILL.md` |
| sdd-archive | Archive completed SDD change | `~/.config/opencode/skills/sdd-archive/SKILL.md` |
| sdd-design | Create SDD technical design | `~/.config/opencode/skills/sdd-design/SKILL.md` |
| sdd-explore | Explore SDD ideas before proposing | `~/.config/opencode/skills/sdd-explore/SKILL.md` |
| sdd-init | Bootstrap SDD context, testing capabilities, registry | `~/.config/opencode/skills/sdd-init/SKILL.md` |
| sdd-onboard | Walk through SDD cycle on real codebase | `~/.config/opencode/skills/sdd-onboard/SKILL.md` |
| sdd-propose | Create change proposals from explorations | `~/.config/opencode/skills/sdd-propose/SKILL.md` |
| sdd-spec | Write delta specs with requirements/scenarios | `~/.config/opencode/skills/sdd-spec/SKILL.md` |
| sdd-tasks | Break change into implementation tasks | `~/.config/opencode/skills/sdd-tasks/SKILL.md` |
| sdd-verify | Validate implementation against specs | `~/.config/opencode/skills/sdd-verify/SKILL.md` |
| skill-creator | Create LLM-first skills | `~/.config/opencode/skills/skill-creator/SKILL.md` |
| skill-improver | Audit/upgrade existing skills | `~/.config/opencode/skills/skill-improver/SKILL.md` |
| skill-registry | Update this registry | `~/.config/opencode/skills/skill-registry/SKILL.md` |
| systemic-issue-triage | Atacar issues por clase raiz | `~/.config/opencode/skills/systemic-issue-triage/SKILL.md` |
| work-unit-commits | Commits como work units reviewables | `~/.config/opencode/skills/work-unit-commits/SKILL.md` |

## Built-in skills (no path required)

| Skill | Trigger |
| --- | --- |
| customize-opencode | Edit OpenCode own config (opencode.json, agents, MCP servers) |

## Project-specific

No project-specific skills registered yet. Add under `.atl/skills/<name>/SKILL.md`
and document the trigger here when the team adds new skills that live in
this repo.

## Resolution notes for sub-agents

- ALL sub-agent launches that touch code MUST include pre-resolved `SKILL.md`
  paths from this registry. The orchestrator resolves skills once per session
  and passes matching paths into each sub-agent prompt.
- For chained PRs / stacked PR workflows (F08 case), `chained-pr` is a
  MANDATORY skill match: it MUST be resolved and its `SKILL.md` path
  passed into `sdd-tasks` and `sdd-apply` before they plan or create any PR.
- For backend code that touches FastAPI routers, SQLAlchemy models, or LLM
  modules under `app/core/llm_*`, no extra skill is required beyond the
  project conventions documented in `openspec/config.yaml` rules.apply.
- For frontend work that touches React components, Zustand stores, or Vite
  build, no extra skill is required either.
- This file is regenerable at any time by re-scanning `<available_skills>`
  from the orchestrator system prompt; treat it as cache, not source of truth.
