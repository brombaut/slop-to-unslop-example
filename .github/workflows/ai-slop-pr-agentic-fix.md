---
name: Code Quality PR Agentic Fix
description: Scan PR base/head, report introduced findings, fix introduced AI Slop and PyExamine findings, merge patches, and open a cleanup PR into the original PR head branch when a non-empty generated fix applies cleanly.

on:
  pull_request:
    types: [opened, synchronize, reopened]
    paths:
      - "**/*.py"
      - "pyproject.toml"
      - "requirements*.txt"
      - "setup.py"
      - "setup.cfg"
  workflow_dispatch:

permissions:
  contents: read
  actions: read
  pull-requests: read

engine:
  id: copilot
  env:
    COPILOT_PROVIDER_BASE_URL: ${{ secrets.COPILOT_PROVIDER_BASE_URL }}
    COPILOT_PROVIDER_API_KEY: ${{ secrets.COPILOT_PROVIDER_API_KEY }}
    COPILOT_PROVIDER_TYPE: openai
    COPILOT_PROVIDER_WIRE_API: responses
    COPILOT_MODEL: ${{ vars.COPILOT_MODEL || 'gpt-5-mini' }}

strict: true
timeout-minutes: 90
max-turns: 8

network:
  allowed:
    - github
    - arcyleung-ubuntu.tailb940e6.ts.net

checkout: false

tools:
  bash: [cat, jq, wc]

safe-outputs:
  threat-detection: false
  mentions: false
  allowed-github-references: []
  create-issue:
    title-prefix: "[Code Quality] "
    max: 1
  create-pull-request:
    title-prefix: "Apply code quality fixes"
    draft: false
    max: 1
    base-branch: ${{ github.event.pull_request.head.ref }}
    allowed-branches:
      - code-quality/agentic-fix-pr-*
    fallback-as-issue: false
    auto-close-issue: false
    max-patch-files: 100
    max-patch-size: 4096

steps:
  - name: Initialize workflow state
    run: |
      set -euo pipefail
      mkdir -p /tmp/repo-analysis
      mkdir -p /tmp/gh-aw/agent
      {
        echo "CAN_REMEDIATE=false"
        echo "SHOULD_FIX=false"
        echo "SHOULD_MERGE=false"
        echo "SHOULD_CREATE_PR=false"
      } >> "$GITHUB_ENV"
      printf '{"shouldCreatePr": false, "reason": "workflow did not reach patch application"}\n' > /tmp/gh-aw/agent/create-pr-request.json

  - name: Guard unsupported events and fork pull requests
    run: |
      set -euo pipefail
      {
        echo "## Code Quality PR Agentic Fix"
        echo
      } >> "$GITHUB_STEP_SUMMARY"

      if [[ "${{ github.event_name }}" != "pull_request" ]]; then
        {
          echo "No cleanup PR was created."
          echo
          echo "This example currently supports pull_request events only."
        } >> "$GITHUB_STEP_SUMMARY"
        exit 0
      fi

      if [[ "${{ github.event.pull_request.head.repo.full_name }}" != "${{ github.repository }}" ]]; then
        {
          echo "No cleanup PR was created."
          echo
          echo "Fork pull requests are intentionally unsupported because this workflow needs write permission to push a cleanup branch."
        } >> "$GITHUB_STEP_SUMMARY"
        exit 0
      fi

      echo "CAN_REMEDIATE=true" >> "$GITHUB_ENV"

  - name: Checkout PR base commit
    if: env.CAN_REMEDIATE == 'true'
    uses: actions/checkout@v7.0.0
    with:
      path: base
      ref: ${{ github.event.pull_request.base.sha }}
      fetch-depth: 0
      persist-credentials: false

  - name: Checkout PR head commit
    if: env.CAN_REMEDIATE == 'true'
    uses: actions/checkout@v7.0.0
    with:
      path: head
      ref: ${{ github.event.pull_request.head.sha }}
      fetch-depth: 0
      persist-credentials: false

  - name: Checkout patch target branch
    if: env.CAN_REMEDIATE == 'true'
    uses: actions/checkout@v7.0.0
    with:
      path: patch-target
      ref: ${{ github.event.pull_request.head.ref }}
      fetch-depth: 0
      persist-credentials: false

  - name: Checkout repo analyzer
    if: env.CAN_REMEDIATE == 'true'
    uses: actions/checkout@v7.0.0
    with:
      repository: PGCodeLLM/code-health
      path: analyzer
      ref: main
      token: ${{ secrets.REPO_ANALYSIS_TOKEN || github.token }}
      persist-credentials: false

  - name: Analyze base commit
    if: env.CAN_REMEDIATE == 'true'
    env:
      AISLOP_LLM_PROVIDER: ${{ secrets.AISLOP_LLM_PROVIDER || vars.AISLOP_LLM_PROVIDER || 'openai-compatible' }}
      AISLOP_LLM_API_KEY: ${{ secrets.AISLOP_LLM_API_KEY }}
      AISLOP_LLM_MODEL: ${{ secrets.AISLOP_LLM_MODEL || vars.AISLOP_LLM_MODEL }}
      AISLOP_LLM_BASE_URL: ${{ secrets.AISLOP_LLM_BASE_URL || vars.AISLOP_LLM_BASE_URL }}
      AISLOP_LLM_ENDPOINT_URL: ${{ secrets.AISLOP_LLM_ENDPOINT_URL || vars.AISLOP_LLM_ENDPOINT_URL }}
      AISLOP_LLM_TIMEOUT: ${{ secrets.AISLOP_LLM_TIMEOUT || vars.AISLOP_LLM_TIMEOUT }}
    run: |
      set -euo pipefail
      python analyzer/analyze.py \
        --output /tmp/repo-analysis/output/base \
        base \
        --enable-llm-review \
        --llm-max-candidates 2

  - name: Analyze head commit
    if: env.CAN_REMEDIATE == 'true'
    env:
      AISLOP_LLM_PROVIDER: ${{ secrets.AISLOP_LLM_PROVIDER || vars.AISLOP_LLM_PROVIDER || 'openai-compatible' }}
      AISLOP_LLM_API_KEY: ${{ secrets.AISLOP_LLM_API_KEY }}
      AISLOP_LLM_MODEL: ${{ secrets.AISLOP_LLM_MODEL || vars.AISLOP_LLM_MODEL }}
      AISLOP_LLM_BASE_URL: ${{ secrets.AISLOP_LLM_BASE_URL || vars.AISLOP_LLM_BASE_URL }}
      AISLOP_LLM_ENDPOINT_URL: ${{ secrets.AISLOP_LLM_ENDPOINT_URL || vars.AISLOP_LLM_ENDPOINT_URL }}
      AISLOP_LLM_TIMEOUT: ${{ secrets.AISLOP_LLM_TIMEOUT || vars.AISLOP_LLM_TIMEOUT }}
    run: |
      set -euo pipefail
      python analyzer/analyze.py \
        --skip-build \
        --output /tmp/repo-analysis/output/head \
        head \
        --enable-llm-review \
        --llm-max-candidates 2

  - name: Build introduced diagnostics report
    if: env.CAN_REMEDIATE == 'true'
    run: |
      set -euo pipefail

      BASE_JSON="$(find /tmp/repo-analysis/output/base -name '*_codehealth_analysis_*.json' | sort | tail -1)"
      HEAD_JSON="$(find /tmp/repo-analysis/output/head -name '*_codehealth_analysis_*.json' | sort | tail -1)"

      if [[ -z "$BASE_JSON" || -z "$HEAD_JSON" ]]; then
        echo "Could not find analysis JSON outputs" >&2
        find /tmp/repo-analysis -maxdepth 4 -type f -print >&2
        exit 1
      fi

      {
        echo "BASE_JSON=$BASE_JSON"
        echo "HEAD_JSON=$HEAD_JSON"
      } >> "$GITHUB_ENV"

      python analyzer/scripts/compare-pr-analysis.py \
        --base "$BASE_JSON" \
        --head "$HEAD_JSON" \
        --output /tmp/repo-analysis/report.md \
        --introduced-json /tmp/repo-analysis/introduced-diagnostics.json

      cat /tmp/repo-analysis/introduced-diagnostics.json > /tmp/gh-aw/agent/introduced-diagnostics.json
      cat /tmp/repo-analysis/report.md >> "$GITHUB_STEP_SUMMARY"

  - name: Build introduced-only fix evidence
    if: env.CAN_REMEDIATE == 'true'
    run: |
      set -euo pipefail

      python analyzer/scripts/build-introduced-fix-analysis.py \
        --head "$HEAD_JSON" \
        --introduced /tmp/repo-analysis/introduced-diagnostics.json \
        --output /tmp/repo-analysis/introduced-fix-analysis.json

      fixable_count="$(jq '((.aislop.diagnostics // []) | length) + ((.pyexamine.findings // []) | length)' /tmp/repo-analysis/introduced-fix-analysis.json)"
      introduced_count="$(jq '.introducedDiagnostics // 0' /tmp/repo-analysis/introduced-fix-analysis.json)"
      ignored_count="$(jq '.ignoredDiagnostics // 0' /tmp/repo-analysis/introduced-fix-analysis.json)"

      {
        echo "INTRODUCED_COUNT=$introduced_count"
        echo "FIXABLE_COUNT=$fixable_count"
        echo "IGNORED_COUNT=$ignored_count"
      } >> "$GITHUB_ENV"

      if [[ "$fixable_count" -eq 0 ]]; then
        {
          echo
          echo "## Agentic Fix"
          echo
          echo "No cleanup PR was created."
          echo
          echo "Introduced findings: $introduced_count"
          echo "Findings supported by the remediation input: 0"
          echo "Ignored unknown-source findings: $ignored_count"
        } >> "$GITHUB_STEP_SUMMARY"
        exit 0
      fi

      echo "SHOULD_FIX=true" >> "$GITHUB_ENV"

  - name: Build analyzer image with Codex
    if: env.SHOULD_FIX == 'true'
    run: |
      set -euo pipefail
      docker build \
        --build-arg INSTALL_CODEX=1 \
        -t repo-analysis-prototype \
        analyzer

  - name: Generate agentic fix patches
    if: env.SHOULD_FIX == 'true'
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      OPENAI_BASE_URL: ${{ secrets.OPENAI_BASE_URL || vars.OPENAI_BASE_URL }}
      AGENTIC_AGENT: codex
      AGENTIC_TIMEOUT: ${{ vars.AGENTIC_TIMEOUT || '1800' }}
      AGENTIC_CODEX_MODEL: ${{ secrets.AGENTIC_CODEX_MODEL || vars.AGENTIC_CODEX_MODEL }}
      AGENTIC_CODEX_BASE_URL: ${{ secrets.AGENTIC_CODEX_BASE_URL || vars.AGENTIC_CODEX_BASE_URL }}
      AGENTIC_CODEX_WIRE_API: ${{ vars.AGENTIC_CODEX_WIRE_API || 'responses' }}
    run: |
      set -euo pipefail
      analyzer/docker/agentic-fix-codebase \
        --skip-build \
        --analysis-json /tmp/repo-analysis/introduced-fix-analysis.json \
        --output /tmp/repo-analysis/agentic-fixes \
        patch-target \
        --source aislop pyexamine \
        --agent codex \
        --limit 5 \
        --jobs 2

      if [[ -f analyzer/scripts/summarize-agentic-fix.py && -f /tmp/repo-analysis/agentic-fixes/run-full.json ]]; then
        python analyzer/scripts/summarize-agentic-fix.py \
          --run-full /tmp/repo-analysis/agentic-fixes/run-full.json \
          --output /tmp/repo-analysis/agentic-fix-summary.md
        cat /tmp/repo-analysis/agentic-fix-summary.md >> "$GITHUB_STEP_SUMMARY"
      fi

  - name: Check agentic fix output
    if: env.SHOULD_FIX == 'true'
    run: |
      set -euo pipefail

      if [[ ! -f /tmp/repo-analysis/agentic-fixes/run.json ]]; then
        {
          echo
          echo "## Patch Merge"
          echo
          echo "No cleanup PR was created because agentic-fix did not write a run manifest."
        } >> "$GITHUB_STEP_SUMMARY"
        exit 0
      fi

      tasks_total="$(jq '.tasksTotal // 0' /tmp/repo-analysis/agentic-fixes/run.json)"
      needs_review="$(jq '.needsReview // 0' /tmp/repo-analysis/agentic-fixes/run.json)"
      unsupported="$(jq '.unsupported // 0' /tmp/repo-analysis/agentic-fixes/run.json)"

      {
        echo "FIX_TASKS_TOTAL=$tasks_total"
        echo "FIX_NEEDS_REVIEW=$needs_review"
        echo "FIX_UNSUPPORTED=$unsupported"
      } >> "$GITHUB_ENV"

      if [[ "$tasks_total" -eq 0 || "$needs_review" -eq 0 ]]; then
        {
          echo
          echo "## Patch Merge"
          echo
          echo "No cleanup PR was created because there were no reviewable fix patches."
          echo
          echo "Selected tasks: $tasks_total"
          echo "Reviewable patches: $needs_review"
          echo "Unsupported selected findings: $unsupported"
        } >> "$GITHUB_STEP_SUMMARY"
        exit 0
      fi

      echo "SHOULD_MERGE=true" >> "$GITHUB_ENV"

  - name: Merge generated patches
    if: env.SHOULD_MERGE == 'true'
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      OPENAI_BASE_URL: ${{ secrets.OPENAI_BASE_URL || vars.OPENAI_BASE_URL }}
      AGENTIC_AGENT: codex
      AGENTIC_TIMEOUT: ${{ vars.AGENTIC_TIMEOUT || '1800' }}
      AGENTIC_CODEX_MODEL: ${{ secrets.AGENTIC_CODEX_MODEL || vars.AGENTIC_CODEX_MODEL }}
      AGENTIC_CODEX_BASE_URL: ${{ secrets.AGENTIC_CODEX_BASE_URL || vars.AGENTIC_CODEX_BASE_URL }}
      AGENTIC_CODEX_WIRE_API: ${{ vars.AGENTIC_CODEX_WIRE_API || 'responses' }}
    run: |
      set -euo pipefail
      analyzer/docker/merge-patches-codebase \
        --skip-build \
        --output /tmp/repo-analysis/merged \
        patch-target \
        /tmp/repo-analysis/agentic-fixes \
        --agent codex

  - name: Check merged patch availability
    if: env.SHOULD_MERGE == 'true'
    run: |
      set -euo pipefail

      if [[ ! -s /tmp/repo-analysis/merged/combined.diff ]]; then
        {
          echo
          echo "## Cleanup PR"
          echo
          echo "No cleanup PR was created because patch merge produced no combined diff."
        } >> "$GITHUB_STEP_SUMMARY"
        exit 0
      fi

      echo "SHOULD_CREATE_PR=true" >> "$GITHUB_ENV"

  - name: Prepare cleanup PR workspace
    if: env.SHOULD_CREATE_PR == 'true'
    run: |
      set -euo pipefail
      rm -rf base head analyzer patch-target

  - name: Checkout cleanup PR base branch
    if: env.SHOULD_CREATE_PR == 'true'
    uses: actions/checkout@v7.0.0
    with:
      ref: ${{ github.event.pull_request.head.ref }}
      fetch-depth: 0
      persist-credentials: false

  - name: Apply merged patch to cleanup PR workspace
    if: env.SHOULD_CREATE_PR == 'true'
    run: |
      set -euo pipefail

      if ! git apply --check /tmp/repo-analysis/merged/combined.diff; then
        {
          echo
          echo "## Cleanup PR"
          echo
          echo "No cleanup PR was created because the combined diff did not apply cleanly to a fresh checkout of the PR head branch."
        } >> "$GITHUB_STEP_SUMMARY"
        echo "SHOULD_CREATE_PR=false" >> "$GITHUB_ENV"
        printf '{"shouldCreatePr": false, "reason": "combined diff did not apply cleanly"}\n' > /tmp/gh-aw/agent/create-pr-request.json
        exit 0
      fi

      git apply /tmp/repo-analysis/merged/combined.diff

      if [[ -z "$(git status --porcelain)" ]]; then
        {
          echo
          echo "## Cleanup PR"
          echo
          echo "No cleanup PR was created because the combined diff produced no staged changes."
        } >> "$GITHUB_STEP_SUMMARY"
        echo "SHOULD_CREATE_PR=false" >> "$GITHUB_ENV"
        printf '{"shouldCreatePr": false, "reason": "combined diff produced no changes"}\n' > /tmp/gh-aw/agent/create-pr-request.json
        exit 0
      fi

  - name: Create cleanup PR body
    if: env.SHOULD_CREATE_PR == 'true'
    env:
      ORIGINAL_PR_NUMBER: ${{ github.event.pull_request.number }}
      ORIGINAL_PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}
      ORIGINAL_PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}
      ORIGINAL_PR_HEAD_REF: ${{ github.event.pull_request.head.ref }}
      WORKFLOW_RUN_ID: ${{ github.run_id }}
    run: |
      set -euo pipefail

      cleanup_branch="code-quality/agentic-fix-pr-${ORIGINAL_PR_NUMBER}-${WORKFLOW_RUN_ID}"
      git switch -c "$cleanup_branch"
      git config user.name "github-actions[bot]"
      git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
      git add -A
      git commit -m "Apply generated code quality fixes for PR #${ORIGINAL_PR_NUMBER}"

      python - <<'PY'
      import json
      import os
      from pathlib import Path

      def env_count(name: str) -> str:
          return os.environ.get(name, "0")

      def merge_count(name: str) -> int:
          path = Path("/tmp/repo-analysis/merged/merge-report.json")
          if not path.exists():
              return 0
          payload = json.loads(path.read_text(encoding="utf-8"))
          value = payload.get(name, 0)
          return value if isinstance(value, int) else 0

      pr_number = os.environ["ORIGINAL_PR_NUMBER"]
      base_sha = os.environ["ORIGINAL_PR_BASE_SHA"]
      head_sha = os.environ["ORIGINAL_PR_HEAD_SHA"]
      head_ref = os.environ["ORIGINAL_PR_HEAD_REF"]
      run_id = os.environ["WORKFLOW_RUN_ID"]

      title = f"Apply code quality fixes for PR #{pr_number}"
      branch = f"code-quality/agentic-fix-pr-{pr_number}-{run_id}"
      body = f"""This PR applies generated code quality fixes for the original pull request.

      ## Original Pull Request

      - PR: #{pr_number}
      - Base SHA: `{base_sha}`
      - Head SHA analyzed: `{head_sha}`
      - Target branch: `{head_ref}`

      ## Remediation Summary

      - Introduced findings: {env_count("INTRODUCED_COUNT")}
      - Findings passed to remediation: {env_count("FIXABLE_COUNT")}
      - Selected fix tasks: {env_count("FIX_TASKS_TOTAL")}
      - Reviewable patches: {env_count("FIX_NEEDS_REVIEW")}
      - Merged patch entries: {merge_count("patchesTotal")}
      - Applied without conflict: {merge_count("patchesApplied")}
      - Merged by agent: {merge_count("patchesMergedByAgent")}

      This cleanup PR targets the original PR head branch so the original PR updates after this PR is merged.
      """
      Path("/tmp/repo-analysis/cleanup-pr-body.md").write_text(body, encoding="utf-8")
      Path("/tmp/gh-aw/agent/create-pr-request.json").write_text(
          json.dumps(
              {
                  "shouldCreatePr": True,
                  "title": title,
                  "branch": branch,
                  "body": body,
              },
              indent=2,
              sort_keys=True,
          )
          + "\n",
          encoding="utf-8",
      )
      PY

      {
        echo
        echo "## Cleanup PR"
        echo
        echo "Prepared a cleanup PR request for the safe-outputs create-pull-request handler."
        echo
        echo "The cleanup PR will target \`${ORIGINAL_PR_HEAD_REF}\`, the source branch of PR #${ORIGINAL_PR_NUMBER}."
      } >> "$GITHUB_STEP_SUMMARY"

  - name: Upload code quality remediation artifacts
    if: always()
    uses: actions/upload-artifact@v7.0.1
    with:
      name: code-quality-pr-agentic-fix-${{ github.run_id }}
      path: |
        /tmp/repo-analysis/
        /tmp/gh-aw/agent/create-pr-request.json
      retention-days: 14
      if-no-files-found: warn
---

# Code Quality PR Agentic Fix

The deterministic workflow steps have already scanned the PR base and head,
filtered introduced findings, written the introduced diagnostics report, run
agentic fix generation, merged eligible patches, and applied the combined diff
to the workspace when a reviewable patch was available.

First, read `/tmp/gh-aw/agent/introduced-diagnostics.json`.

If the introduced diagnostics file exists, is valid, and contains introduced
diagnostics or findings, create exactly one issue using the `create_issue` safe
output.

The issue title must be:

`Summary for PR #${{ github.event.pull_request.number }}`

The issue body must include these sections:

## Summary

A short explanation that this issue collects all AI Slop diagnostics and
PyExamine findings introduced by this pull request in one report.

## Pull Request

- PR: #${{ github.event.pull_request.number }}
- Base SHA: `${{ github.event.pull_request.base.sha }}`
- Head SHA: `${{ github.event.pull_request.head.sha }}`

## Introduced Findings

A markdown table with one row per introduced diagnostic or finding. Preserve the
order from the JSON file. The columns must be:

- Rule
- File
- Line
- Source
- Message

Keep messages concise enough that the table remains readable. Do not omit
diagnostics or findings from this table.

## Detailed Findings

For each item in `introduced_diagnostics`, include a short subsection using this
heading format:

`### <rule> in <filePath>:<line>`

Each subsection must include:

- Source: `<analysisSource>`
- Message: the diagnostic or finding message from the analyzer
- Related locations: include related locations when `relatedLocations` is
  present and non-empty. If none are present, write `None`.
- Suggested follow-up: one concise, actionable recommendation based on the
  diagnostic or finding fields. Prefer the `help` field when it is present.
  Do not invent source code changes that are not supported by the diagnostic or
  finding.

## Counts By Source And Rule

A markdown table with one row per source/rule pair and the number of introduced
diagnostics or findings for that pair.

Use only the diagnostics and findings in
`/tmp/gh-aw/agent/introduced-diagnostics.json`. Do not create issues for
existing base diagnostics or findings, resolved diagnostics or findings,
code-health regressions, items outside that JSON file, or general
recommendations.

Next, read `/tmp/gh-aw/agent/create-pr-request.json`.

If the create-PR request file is missing, invalid, or has `shouldCreatePr` set
to anything other than `true`, do not call `create_pull_request`.

If `shouldCreatePr` is `true`, call `create_pull_request` exactly once using
only these fields from the JSON file:

- `title`
- `body`
- `branch`

Do not edit repository files, create additional branches with git commands,
open additional pull requests, comment on the original pull request, or change
the prepared title/body/branch. Apart from the single scan issue described
above, do not create issues. The pull request base branch is configured in
`safe-outputs.create-pull-request` and targets the original PR head branch.
