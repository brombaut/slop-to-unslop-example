---
name: Code Quality Issue Reporter
description: Scan PR base/head and create one GitHub issue summarizing AI Slop diagnostics and PyExamine findings introduced by the PR.

on:
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
timeout-minutes: 30
max-turns: 4

network:
  allowed:
    - github
    - arcyleung-ubuntu.tailb940e6.ts.net

checkout:
  - path: base
    ref: ${{ github.event.pull_request.base.sha }}
    fetch-depth: 0
  - path: head
    ref: ${{ github.event.pull_request.head.sha }}
    fetch-depth: 0
  - repository: PGCodeLLM/code-health
    path: analyzer
    ref: main
    github-token: ${{ secrets.REPO_ANALYSIS_TOKEN }}

tools:
  bash: [cat, jq, wc]

steps:
  - name: Analyze base commit
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
    run: |
      set -euo pipefail

      mkdir -p /tmp/gh-aw/agent
      BASE_JSON="$(find /tmp/repo-analysis/output/base -name '*_codehealth_analysis_*.json' | sort | tail -1)"
      HEAD_JSON="$(find /tmp/repo-analysis/output/head -name '*_codehealth_analysis_*.json' | sort | tail -1)"

      if [ -z "$BASE_JSON" ] || [ -z "$HEAD_JSON" ]; then
        echo "Could not find analysis JSON outputs" >&2
        find /tmp/repo-analysis -maxdepth 4 -type f -print >&2
        exit 1
      fi

      python analyzer/scripts/compare-pr-analysis.py \
        --base "$BASE_JSON" \
        --head "$HEAD_JSON" \
        --output /tmp/gh-aw/agent/report.md \
        --introduced-json /tmp/gh-aw/agent/introduced-diagnostics.json

      cat /tmp/gh-aw/agent/report.md >> "$GITHUB_STEP_SUMMARY"

safe-outputs:
  threat-detection: false
  mentions: false
  allowed-github-references: []
  create-issue:
    title-prefix: "[Code Quality] "
    max: 1
    deduplicate-by-title: true
    expires: 30
---

# Code Quality PR Issue Reporter

You are creating one GitHub issue that summarizes the AI Slop diagnostics and
PyExamine findings introduced by this pull request.

Read `/tmp/gh-aw/agent/introduced-diagnostics.json`.

If the file is missing, invalid, empty, or contains no introduced diagnostics or
findings, do not create an issue. Finish without visible GitHub writes.

Create exactly one issue using the `create_issue` safe output.

The issue title must be stable and deterministic:

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

## Notes

State that this issue title is deterministic so repeated workflow runs can
deduplicate by title.

Use only the diagnostics and findings in
`/tmp/gh-aw/agent/introduced-diagnostics.json`. Do not create issues for
existing base diagnostics or findings, resolved diagnostics or findings,
code-health regressions, items outside that JSON file, or general
recommendations.
