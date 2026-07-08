# Slop To Unslop Example

Small Python repository for testing the repo-analysis PR remediation workflow.

The active workflow is a GitHub Agentic Workflow:

- Source: `.github/workflows/ai-slop-pr-agentic-fix.md`
- Compiled workflow: `.github/workflows/ai-slop-pr-agentic-fix.lock.yml`

GitHub Actions runs the compiled `.lock.yml` file. Edit the `.md` source file,
then recompile it before committing workflow changes.

## Workflow Behavior

On pull requests that change Python project files, the workflow:

1. Checks out the PR base revision, PR head revision, and a patch target branch.
2. Checks out the analyzer repository from `PGCodeLLM/code-health`.
3. Runs the repo analyzer on base and head with AI Slop LLM review enabled.
4. Compares the reports and keeps only findings introduced by the PR.
5. Opens one issue report and brief inline PR review comments for introduced
   AI Slop and PyExamine findings.
6. Builds remediation evidence for introduced AI Slop and PyExamine findings.
7. Runs the analyzer's agentic fixer with Codex to generate reviewable patches.
8. Merges eligible patches and opens a cleanup PR back into the original PR
   branch when a non-empty fix applies cleanly.

The workflow uses safe gh-aw outputs for repository writes. It does not push
directly to the original feature branch.

## Compiling The Workflow

Install and authenticate `gh-aw` as described by the GitHub Agentic Workflows
project. From this repository, compile the workflow with:

```bash
gh aw compile
```

This updates `.github/workflows/ai-slop-pr-agentic-fix.lock.yml` from
`.github/workflows/ai-slop-pr-agentic-fix.md`. Commit both files whenever the
workflow source changes.

## Analyzer Checkout

The workflow currently checks out:

```yaml
repository: PGCodeLLM/code-health
ref: main
```

If that repository is private, add a repository secret named
`REPO_ANALYSIS_TOKEN` with read access to `PGCodeLLM/code-health`.

## Local Smoke Test

From this repository, after the analyzer repository exists at
`../repo-analysis-prototype` or another local path:

```bash
python ../repo-analysis-prototype/analyze.py \
  --output /tmp/repo-analysis/output/head \
  .
```

## PR Test Shape

1. Push this repository to GitHub.
2. Keep `main` clean of analyzer findings.
3. Open a pull request from a branch that introduces AI Slop or PyExamine
   findings.
4. Inspect the workflow step summary, uploaded artifacts, and generated cleanup
   PR.
