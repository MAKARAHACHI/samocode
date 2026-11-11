# Task: Bounded unattended self-recovery for SAMOCODE + Hermes

**Status:** Proposed · **Scope:** One focused implementation task · **Priority:** High
**Owner of workflow transitions:** Original SAMOCODE worker (unchanged)
**Reference acceptance:** [Agorot QA and GitHub PR #1](https://github.com/MAKARAHACHI/samocode/pull/1)

## Problem
The end-to-end agorot pilot successfully reached original SAMOCODE `done`, independent ChatGPT QA PASS, and a published GitHub PR, but Hermes required an additional manual recovery instruction. The final success proves the pipeline; it does not prove unattended recovery from known preflight blockers.

Observed blockers:
1. ChatGPT CDP was rejected because an old developer-conversation tab and root tab both existed.
2. Hermes's isolated `HOME` could not see already-authenticated GitHub CLI configuration.
3. Python test execution created an untracked bytecode cache, leaving the repository dirty.

## Required behavior
Implement a **bounded, allowlisted, restart-safe preflight recovery** inside the existing Hermes/SAMOCODE integration. The original SAMOCODE worker remains the sole workflow transition authority. No alternate scheduler, API provider, Docker, or broad infrastructure rebuild.

### A. Browser CDP recovery
- Inspect actual ChatGPT `page` targets, IDs and URLs before creating a browser operation.
- Close **only** the exact eligible *historical developer* target when a previously approved provenance/allowlist matches both target ID and URL, and the intended root tab is unambiguous.
- Never close unknown/unapproved tabs. If target identity is uncertain, stop safely with an actionable error.
- After an eligible closure, verify exactly one ChatGPT tab, then rerun existing `inspect-ui` and `ensure-model --model gpt-6 --effort high`. Never bypass these gates.
- Preserve the browser operation ledger; never resend a potentially delivered or uncertain message. On restart, read back a completed result instead of repeating.

### B. GitHub CLI recovery
- Reuse only the operator-approved existing GitHub CLI configuration via `GH_CONFIG_DIR` within Hermes's isolated `HOME`.
- Verify `gh auth status`, target repository, branch and push permissions before publishing.
- No new login, secret copying/printing, or force-push. Stop if access cannot be verified.

### C. Python cache hygiene
- Set `PYTHONDONTWRITEBYTECODE=1` for all validation runs.
- Clean only proven generated **untracked** bytecode files inside an approved project directory. Do not delete source, tracked files, symlinks, or unexpected user files.
- Stop and report if cleanup is ambiguous.

### D. Admission & evidence
- Keep immutable SHA256 evidence for reviewed source and tests.
- Enforce: original SAMOCODE session is `done` → clean/hash-matched local repo → GPT-6 High preflight → exactly one fresh independent QA conversation with complete verified response → QA PASS → authorized branch/push → verified PR.
- Ensure no duplicate browser sends, QA conversations, branches or PRs across retries/crash recovery. Bounded retries only.
- Emit a machine-readable receipt: reconciliation actions, original/new target IDs, exact policy match, operation ID, QA URL/verdict, source/test hashes, Git SHAs, PR URL, or specific fail-closed blocker.

## Acceptance tests
- [ ] Simulated known two-tab configuration recovers; unknown/ambiguous tabs remain open and fail closed.
- [ ] Second preflight failure stops; cannot falsely claim GPT-6 High.
- [ ] Existing GitHub CLI auth works under isolated `HOME`; invalid/missing auth stops without leaking credentials.
- [ ] Untracked generated cache is handled safely; tracked files and symlinks never removed.
- [ ] Interrupted/uncertain operation tests prove at-most-once send and PR creation.
- [ ] Unit/regression tests all pass with no repository dirtiness.
- [ ] **One separately approved live end-to-end acceptance**, starting from the three known blockers, completes without an additional operator recovery prompt; records distinct QA conversation URL with PASS and an authentic remote PR. An unknown blocker must stop rather than improvise.
- [ ] Documentation records allowlist policy, operator configuration, bounded recovery and escalation conditions.

## Non-goals
No arbitrary tab closure, bypassing safety checks, generic autonomous host repair, automatic PR merge, new SAMOCODE workflow engine, or changes to the already completed agorot session.

## Definition of done
Reviewed implementation PR + passing regression suite + one new owner-authorized uninterrupted final acceptance with saved receipts. This task is **not** complete just because the original pilot succeeded.
