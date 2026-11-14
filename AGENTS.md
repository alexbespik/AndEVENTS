# Agent Team Architecture & Workflow Rules

You have access to a specialized team of autonomous subagents. Use them to maintain high code quality, strict architectural boundaries, thorough verification, and complete security compliance.

## Available Agents

| Agent | Type | Capabilities & Purpose |
| :--- | :--- | :--- |
| `researcher` | Read-only | Researches the codebase, official docs, and libraries; evaluates trade-offs; creates step-by-step implementation plans. |
| `architect` | Read-only* | Systems & infrastructure design, module boundaries, APIs, data contracts, config, build/deploy, performance, and scaling. (*Edits only architecture documentation). |
| `overseer` | Read-only | Quality & safety gatekeeper. Evaluates plans before code changes (PLAN) and validates completed work against real test outputs (DONE). |
| `coder` | Implementer | Writes and edits code following approved plans; keeps diffs small and surgical; coordinates with tester and reviewer. |
| `tester` | Read-only | Executes test suites, linters, type checks, and builds in a restricted environment; reports exact failures. |
| `reviewer` | Read-only | Defect-first code reviewer for diffs; catches logic flaws, edge cases, contract mismatches, and unhandled exceptions. |
| `security` | Read-only | Security auditor; scans diffs for secrets, OWASP vulnerabilities (injection, auth, XSS, SSRF, IDOR), and unsafe operations. |
| `explorer` | Read-only | Fast codebase search; finds symbols, definitions, usages, and references in file:line format. |
| `bookkeeper` | Data Worker | Database schemas, migrations, seed imports, backups, and integrity checks (SQLite/Postgres, CSV, JSON). |

## Task Sizing

Before executing work, classify the task:
- **Small Task**: 1 file, under ~30 changed lines, no config/infra/dependency changes, behavior straightforward.
  -> Implement directly or with `coder`, then verify with `tester`.
- **Complex Task**: Any of the following:
  * 3+ files or 2+ components (e.g., frontend + backend, server + DB).
  * New feature, route, API schema, database table, or data format.
  * Any config, env var, dependency, build, deploy, or infra change.
  * DB/schema migration.
  * Performance or scaling optimization.
  * Unclear requirements or multiple viable approaches.

## Multi-Agent Execution Flow for Complex Tasks

1. **Research & Planning**: Invoke `researcher` with the user request verbatim.
2. **Architecture Review** (if 2+ components, API contracts, configs, schema, or infra are involved): Invoke `architect` with the researcher plan.
3. **Plan Quality Gate**: Invoke `overseer` (CHECKPOINT: PLAN). Only proceed if verdict is `PROCEED`.
4. **Implementation**: Invoke `coder` with the agreed plan.
5. **Parallel Verification**:
   - Run `tester` to verify unit/integration tests and type checks.
   - Run `reviewer` to inspect the code diff for logic errors and regressions.
6. **Security Audit**: Invoke `security` before any commit, dependency change, or multi-file completion. Must return `PASS` or `WARN` (never `BLOCK`).
7. **Final Quality Gate**: Invoke `overseer` (CHECKPOINT: DONE) with empirical test results and diff summary.

## Operational Guardrails

- **Zero Secret Exposure**: Never write, echo, or log credentials, tokens, or private keys.
- **Empirical Evidence**: Never claim tests or builds pass without running them and reporting actual outputs.
- **Strict Scope Discipline**: Implement only what was requested. Avoid unsolicited refactors or unused dependencies.
