# Universal Agent Contract
**Ecosystem Standard for Claude Code, Antigravity, Gemini, Cursor & Human Collaborators**

---

## 1. Authority and Intent

1. The current user prompt is the primary work authority.
2. Safety, security, data-loss protection, and platform correctness remain mandatory.
3. Prior handoffs, old TODOs, and previous agent claims are planning evidence only; never let them block a direct request.
4. Code is reality; documentation defines requirements. When they disagree, trust the active code and report or repair the gap.
5. Preserve unrelated user work. Do not stage, commit, reset, clean, or check out unless explicitly instructed.

---

## 2. Universal Understanding of Directives

Interpret natural instructions decisively:
- **"Fix this" / "make it work" / "take ownership"**: Diagnose root causes, implement solutions, and verify using appropriate tests.
- **"Continue" / "keep going" / "resume"**: Continue the current in-scope objective using verified evidence.
- **"Focus on X" / "stop Y"**: Prioritize X and pause Y while preserving all existing progress.
- **"Audit" / "takeover"**: Inspect relevant requirements and owning code, fix evidenced issues, and verify.
- **"Skip Git" / "don't rebuild"**: Strictly omit unnecessary Git operations or builds.

---

## 3. Engineering Invariants & Code Hygiene

1. **Architecture Separation**: Thin routing layers; business logic resides in dedicated services, stores, hooks, or native modules.
2. **Design System Adherence**: Respect unified design tokens (Warm Terracotta, Bone White, Deep Slate, Squircles). Never create ad-hoc palette islands.
3. **Secrets & Credentials**: Never hardcode API keys, passwords, or tokens into code, git history, or public logs. Use secure environment variables.
4. **Verification Discipline**: Validate every change with the narrowest reliable check (`tsc --noEmit`, linters, or test suites) before completing a task.
5. **No Ephemeral Status Docs**: Do not pollute the repository with temporary markdown status dumps or handoff scratchpads. Durable rules belong in rulebooks, procedures in skills, and progress in conversation.

---

## 4. Git Commit Standards

When commits are requested, follow the standard convention enforced across the ecosystem:
- **Format**: `type(scope): imperative summary`
- **Allowed Types**: `feat | fix | chore | refactor | docs | test | perf`
- **Rules**: Maximum 72 characters for subject, lowercase, no trailing period.
- **Body**: Required after a blank line. State what was changed and why in clear bullet points.
- **Scope Discipline**: Stage only files relevant to the specific change. Never mix unrelated edits.
