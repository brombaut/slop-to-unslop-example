---
name: AI Slop Issue Reporter
description: Scan PR base/head and create GitHub issues for AI Slop diagnostics introduced by the PR.

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
timeout-minutes: 30
max-turns: 4

network:
  allowed:
    - github
    - api.openai.com

checkout:
  - path: base
    ref: ${{ github.event.pull_request.base.sha || github.sha }}
    fetch-depth: 0
  - path: head
    ref: ${{ github.event.pull_request.head.sha || github.sha }}
    fetch-depth: 0
  - repository: PGCodeLLM/code-health
    path: analyzer
    ref: main
    github-token: ${{ secrets.REPO_ANALYSIS_TOKEN }}

tools:
  bash: [cat, jq, wc]

steps:
  - name: Analyze base commit
    run: |
      set -euo pipefail
      python analyzer/analyze.py \
        --output /tmp/repo-analysis/output/base \
        base

  - name: Analyze head commit
    run: |
      set -euo pipefail
      python analyzer/analyze.py \
        --skip-build \
        --output /tmp/repo-analysis/output/head \
        head

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
  mentions: false
  allowed-github-references: []
  create-issue:
    title-prefix: "[AI Slop] "
    max: 10
    deduplicate-by-title: true
    expires: 30
---

# AI Slop PR Issue Reporter

You are creating GitHub issues for AI Slop diagnostics introduced by this pull
request.

Read `/tmp/gh-aw/agent/introduced-diagnostics.json`.

If the file is missing, invalid, empty, or contains no introduced diagnostics,
do not create issues. Finish without visible GitHub writes.

For each item in `introduced_diagnostics`, create one GitHub issue using the
`create_issue` safe output. Create at most 10 issues. Preserve the order from
the JSON file.

Each issue title must be stable and deterministic:

`<rule> in <filePath>:<line> from PR #${{ github.event.pull_request.number }}`

Each issue body must include these sections:

## Summary

A short explanation that this pull request introduced the diagnostic.

## Location

- PR: #${{ github.event.pull_request.number }}
- File: `<filePath>`
- Line: `<line>`
- Rule: `<rule>`
- Source: `<analysisSource>`

## Diagnostic Message

The diagnostic message from the analyzer.

## Related Locations

Include related locations when `relatedLocations` is present and non-empty. If
none are present, write `None`.

## Suggested Follow-Up

One concise, actionable recommendation based on the diagnostic fields. Prefer
the diagnostic `help` field when it is present. Do not invent source code
changes that are not supported by the diagnostic.

Use only the diagnostics in `/tmp/gh-aw/agent/introduced-diagnostics.json`.
Do not create issues for existing base diagnostics, resolved diagnostics,
code-health regressions, PyExamine findings, or general recommendations.
