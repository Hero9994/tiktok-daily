# AGENTS.md — Zero-Waste CI / GitHub Actions Policy

This repository follows the owner's mandatory **Local/Workspace First** development policy.
These instructions apply to every agent (including ChatGPT and Codex) working here.
**Goal:** minimize GitHub Actions minutes and paid build resources while preserving correctness, security, required checks, and release quality.

## Required workflow

1. **Inspect before changing anything.** Identify the project stack and available local tooling. Check relevant `.github/workflows/*.yml` / `*.yaml` for `push`, `pull_request`, `workflow_dispatch`, schedules, path filters, and potentially expensive jobs **before** planning a push, PR, or merge. Check existing branch protection/required status checks when accessible; if not, say what remains unknown.
2. **Work and test locally first.** Prefer the current workspace, Codex environment, local shell, or already-provisioned development container. Run targeted lint, type checking, unit tests, static/security checks, and builds appropriate for the changed code. Use the project's actual commands; do not invent successes or assume tools are installed.
3. **Scale checks to the change.** Start with affected modules and fast checks; run broader local tests when risk warrants. Preserve mandatory security and release validations. Do not replace meaningful verification with a claim that the change is small.
4. **Avoid CI as a development loop.** Never use repeated push → CI failure → edit → push cycles as the primary debugging method. Diagnose and fix from local test output and existing logs first. Do not trigger, dispatch, or rerun GitHub Actions solely to verify something that can be validated in the workspace.
5. **Batch changes.** Complete implementation and local verification before uploading. Prefer one coherent push over many incremental pushes; do not open or update PRs repeatedly just to obtain CI feedback. Avoid unnecessary commit/push activity that would trigger automatic workflows.
6. **APK / Android builds.** Prefer an available local Android SDK, Gradle, Java toolchain, emulator, or workspace/cloud development environment for debug APKs and targeted Android tests. Use Actions for an APK only if local execution is unavailable or a genuinely necessary release gate requires it.
7. **Cloud cost discipline.** A different cloud runner is not automatically free. Check resource availability, quotas, likely costs, and permission before moving a heavy job to another hosted platform. Prefer existing, already-available development resources.
8. **Workflow optimizations (only when in scope and safe).** Consider correct `paths` / `paths-ignore`, `concurrency` with cancellation of superseded *non-release* runs, dependency caches, job conditions, and bounded timeouts. Do not modify workflows, required checks, branch protection, security controls, or deployment permissions without assessing the impact and obtaining any required approval.
9. **Never weaken safety or release gates.** Keep security scans, signing checks, mandatory integration/device tests, protected-branch requirements, and deployment approvals intact. Do not cancel releases or other important jobs just to reduce minutes. If existing repository-specific `AGENTS.md` instructions require extra verification, preserve those stronger requirements.
10. **Skip-CI markers are exceptional.** Only consider `[skip ci]` or equivalent for an explicitly documentation-only/non-executable change when that is safe for this repository and cannot impede required PR checks. Do not use it to bypass required validation for source, security, dependency, or release changes.
11. **Approval for expensive runs.** Do not manually dispatch or rerun a costly Actions workflow without the owner's explicit authorization for that run. If indispensable, explain why local alternatives are insufficient and describe the expected cost/risk before asking permission. Automatic triggers must be accounted for *before* a push.
12. **Report truthfully.** At the end of each task, state: local checks actually executed and their results; checks that could not run; whether any GitHub Actions runs were actually initiated or might be automatically triggered; and whether a push or PR was created. Do not assert zero usage without evidence.

**Default sequence:** Local/Workspace First → Verify → Batch Changes → Push Once → GitHub Actions Only When Necessary.

This is a standing policy for routine development, not permission to bypass mandatory CI or release verification.
