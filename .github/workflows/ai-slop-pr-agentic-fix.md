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
  activation-comments: false
  noop:
    report-as-issue: false

jobs:
  publish_code_quality_results:
    name: Publish Code Quality Results
    needs: agent
    if: needs.agent.result == 'success' && github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    permissions:
      actions: read
      contents: write
      issues: write
      pull-requests: write
    steps:
      - name: Download code quality artifacts
        uses: actions/download-artifact@v8.0.1
        with:
          name: code-quality-pr-agentic-fix-${{ github.run_id }}
          path: /tmp/code-quality-artifacts

      - name: Checkout original PR branch
        uses: actions/checkout@v7.0.0
        with:
          ref: ${{ github.event.pull_request.head.ref }}
          fetch-depth: 0
          persist-credentials: false

      - name: Publish report, comments, and cleanup PR
        env:
          GH_TOKEN: ${{ github.token }}
          ORIGINAL_PR_NUMBER: ${{ github.event.pull_request.number }}
          ORIGINAL_PR_HEAD_REF: ${{ github.event.pull_request.head.ref }}
          ORIGINAL_PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}
          GITHUB_REPOSITORY: ${{ github.repository }}
        run: |
          set -euo pipefail

          artifact_root="/tmp/code-quality-artifacts"
          repo_analysis_dir="${artifact_root}/repo-analysis"
          agent_dir="${artifact_root}/gh-aw/agent"

          if [[ ! -d "$repo_analysis_dir" ]]; then
            repo_analysis_dir="$(find "$artifact_root" -type d -name repo-analysis | head -1)"
          fi
          if [[ ! -d "$agent_dir" ]]; then
            agent_dir="$(find "$artifact_root" -type d -path '*/gh-aw/agent' | head -1)"
          fi

          introduced_json="${agent_dir}/introduced-diagnostics.json"
          if [[ ! -f "$introduced_json" ]]; then
            introduced_json="${repo_analysis_dir}/introduced-diagnostics.json"
          fi
          issue_body="${agent_dir}/introduced-findings-issue.md"
          remediation_status="${agent_dir}/remediation-status.json"
          create_pr_request="${agent_dir}/create-pr-request.json"
          cleanup_body="${repo_analysis_dir}/cleanup-pr-body.md"
          combined_diff="${repo_analysis_dir}/merged/combined.diff"

          issue_url=""
          introduced_count=0
          if [[ -f "$introduced_json" ]]; then
            introduced_count="$(jq '(.introduced_diagnostics // []) | length' "$introduced_json")"
          fi

          if [[ "$introduced_count" -gt 0 && -f "$issue_body" ]]; then
            issue_url="$(gh issue create \
              --title "[Code Quality] Summary for PR #${ORIGINAL_PR_NUMBER}" \
              --body-file "$issue_body")"
            echo "Created findings issue: ${issue_url}"
          fi

          if [[ -n "$issue_url" && -f "$cleanup_body" ]]; then
            python - "$cleanup_body" "$issue_url" <<'PY'
          from pathlib import Path
          import sys

          path = Path(sys.argv[1])
          issue_url = sys.argv[2]
          body = path.read_text(encoding="utf-8")
          body = body.replace("#aw_findings", issue_url)
          path.write_text(body, encoding="utf-8")
          PY
          fi

          if [[ "$introduced_count" -gt 0 ]]; then
            python - "$introduced_json" "$remediation_status" "$issue_url" <<'PY'
          import json
          import os
          import subprocess
          import sys
          from pathlib import Path
          from typing import Any

          introduced_path = Path(sys.argv[1])
          status_path = Path(sys.argv[2])
          issue_url = sys.argv[3]
          repo = os.environ["GITHUB_REPOSITORY"]
          pr_number = os.environ["ORIGINAL_PR_NUMBER"]
          head_sha = os.environ["ORIGINAL_PR_HEAD_SHA"]

          def read_object(path: Path) -> dict[str, Any]:
              if not path.exists():
                  return {}
              try:
                  value = json.loads(path.read_text(encoding="utf-8"))
              except json.JSONDecodeError:
                  return {}
              return value if isinstance(value, dict) else {}

          def source_label(source: Any) -> str:
              if source in {"deterministic_static_analysis", "llm_review"}:
                  return "AI Slop"
              if source == "pyexamine":
                  return "PyExamine"
              return "Finding"

          introduced = read_object(introduced_path)
          statuses = read_object(status_path).get("byDiagnosticId")
          if not isinstance(statuses, dict):
              statuses = {}

          for diagnostic in introduced.get("introduced_diagnostics") or []:
              if not isinstance(diagnostic, dict):
                  continue
              path = diagnostic.get("filePath")
              line = diagnostic.get("line")
              rule = diagnostic.get("rule") or "code quality finding"
              diagnostic_id = diagnostic.get("diagnosticId")
              if not isinstance(path, str) or not isinstance(line, int):
                  continue

              status = {}
              if isinstance(diagnostic_id, str):
                  candidate = statuses.get(diagnostic_id)
                  if isinstance(candidate, dict):
                      status = candidate
              comment_status = status.get("commentStatus")
              if not isinstance(comment_status, str) or not comment_status:
                  comment_status = "Remediation status unavailable."

              details = f" See full report: {issue_url}" if issue_url else ""
              body = f"{source_label(diagnostic.get('analysisSource'))}: {rule}. {comment_status}{details}"
              result = subprocess.run(
                  [
                      "gh",
                      "api",
                      f"/repos/{repo}/pulls/{pr_number}/comments",
                      "-f",
                      f"body={body}",
                      "-f",
                      f"commit_id={head_sha}",
                      "-f",
                      f"path={path}",
                      "-F",
                      f"line={line}",
                      "-f",
                      "side=RIGHT",
                  ],
                  text=True,
                  stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE,
                  check=False,
              )
              if result.returncode != 0:
                  print(
                      f"warning: could not create review comment for {path}:{line}: {result.stderr.strip()}",
                      file=sys.stderr,
                  )
          PY
          fi

          should_create_pr="false"
          if [[ -f "$create_pr_request" ]]; then
            should_create_pr="$(jq -r '.shouldCreatePr == true' "$create_pr_request")"
          fi

          if [[ "$should_create_pr" != "true" ]]; then
            echo "No cleanup PR requested."
            exit 0
          fi

          if [[ ! -s "$combined_diff" || ! -f "$cleanup_body" ]]; then
            echo "No cleanup PR created because the merged diff or PR body is missing."
            exit 0
          fi

          cleanup_branch="$(jq -r '.branch // empty' "$create_pr_request")"
          if [[ -z "$cleanup_branch" ]]; then
            echo "No cleanup PR created because create-pr-request.json did not include a branch."
            exit 0
          fi

          git switch -c "$cleanup_branch"
          if ! git apply --check "$combined_diff"; then
            echo "No cleanup PR created because the combined diff did not apply cleanly."
            exit 0
          fi

          git apply "$combined_diff"
          if [[ -z "$(git status --porcelain)" ]]; then
            echo "No cleanup PR created because the combined diff produced no changes."
            exit 0
          fi

          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A
          git commit -m "Apply generated code quality remediation for PR #${ORIGINAL_PR_NUMBER}"
          git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
          git fetch origin "+refs/heads/${cleanup_branch}:refs/remotes/origin/${cleanup_branch}" || true
          git push --force-with-lease origin "$cleanup_branch"

          pr_title="Apply code quality remediation: PR #${ORIGINAL_PR_NUMBER}"
          existing_pr_number="$(gh pr list \
            --head "$cleanup_branch" \
            --base "$ORIGINAL_PR_HEAD_REF" \
            --state open \
            --json number \
            --jq '.[0].number // empty')"

          if [[ -n "$existing_pr_number" ]]; then
            gh pr edit "$existing_pr_number" --title "$pr_title" --body-file "$cleanup_body"
            pr_url="$(gh pr view "$existing_pr_number" --json url --jq .url)"
          else
            pr_url="$(gh pr create \
              --base "$ORIGINAL_PR_HEAD_REF" \
              --head "$cleanup_branch" \
              --title "$pr_title" \
              --body-file "$cleanup_body")"
          fi

          {
            echo "## Published Code Quality Results"
            echo
            if [[ -n "$issue_url" ]]; then
              echo "- Findings issue: ${issue_url}"
            fi
            echo "- Cleanup PR: ${pr_url}"
          } >> "$GITHUB_STEP_SUMMARY"

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
    env:
      PR_NUMBER: ${{ github.event.pull_request.number }}
      WORKFLOW_RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
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
        --introduced-json /tmp/repo-analysis/introduced-diagnostics.json \
        --introduced-issue-output /tmp/gh-aw/agent/introduced-findings-issue.md \
        --pr-number "${{ github.event.pull_request.number }}" \
        --pr-base-sha "${{ github.event.pull_request.base.sha }}" \
        --pr-head-sha "${{ github.event.pull_request.head.sha }}"

      report_header="$(mktemp)"
      {
        echo "> Generated by [Code Quality PR Agentic Fix](${WORKFLOW_RUN_URL}) for PR #${PR_NUMBER}"
        echo
      } > "$report_header"
      cat "$report_header" /tmp/repo-analysis/report.md > /tmp/repo-analysis/report-with-header.md
      cat "$report_header" /tmp/gh-aw/agent/introduced-findings-issue.md > /tmp/gh-aw/agent/introduced-findings-issue-with-header.md
      mv /tmp/repo-analysis/report-with-header.md /tmp/repo-analysis/report.md
      mv /tmp/gh-aw/agent/introduced-findings-issue-with-header.md /tmp/gh-aw/agent/introduced-findings-issue.md

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
      git commit -m "Apply generated code quality remediation for PR #${ORIGINAL_PR_NUMBER}"

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

      title = f"PR #{pr_number}"
      branch = f"code-quality/agentic-fix-pr-{pr_number}-{run_id}"
      body = f"""This PR applies generated code quality remediation for the original pull request.

      ## Original Pull Request

      - PR: #{pr_number}
      - Findings report: #aw_findings
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
        echo "Prepared a cleanup PR request for the deterministic publish job."
        echo
        echo "The cleanup PR will target \`${ORIGINAL_PR_HEAD_REF}\`, the source branch of PR #${ORIGINAL_PR_NUMBER}."
      } >> "$GITHUB_STEP_SUMMARY"

  - name: Build remediation comment statuses
    if: always()
    run: |
      set -euo pipefail

      mkdir -p /tmp/gh-aw/agent

      python - <<'PY'
      import json
      from pathlib import Path
      from typing import Any

      introduced_path = Path("/tmp/gh-aw/agent/introduced-diagnostics.json")
      request_path = Path("/tmp/gh-aw/agent/create-pr-request.json")
      run_full_path = Path("/tmp/repo-analysis/agentic-fixes/run-full.json")
      merge_report_path = Path("/tmp/repo-analysis/merged/merge-report.json")
      output_path = Path("/tmp/gh-aw/agent/remediation-status.json")

      def read_object(path: Path) -> dict[str, Any]:
          if not path.exists():
              return {}
          try:
              payload = json.loads(path.read_text(encoding="utf-8"))
          except json.JSONDecodeError:
              return {}
          return payload if isinstance(payload, dict) else {}

      def read_items(path: Path, key: str) -> list[dict[str, Any]]:
          payload = read_object(path)
          items = payload.get(key)
          if not isinstance(items, list):
              return []
          return [item for item in items if isinstance(item, dict)]

      def strings(values: Any) -> set[str]:
          if not isinstance(values, list):
              return set()
          return {str(value) for value in values if isinstance(value, str) and value}

      def diagnostic_ids_for_task(entry: dict[str, Any]) -> set[str]:
          task = entry.get("task") if isinstance(entry.get("task"), dict) else {}
          result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
          ids: set[str] = set()
          primary = task.get("primaryDiagnosticId")
          if isinstance(primary, str) and primary:
              ids.add(primary)
          primary = result.get("primaryDiagnosticId")
          if isinstance(primary, str) and primary:
              ids.add(primary)
          ids.update(strings(task.get("sourceDiagnosticIds")))
          ids.update(strings(result.get("sourceDiagnosticIds")))
          evidence = task.get("evidence")
          if isinstance(evidence, list):
              for item in evidence:
                  if isinstance(item, dict):
                      diagnostic_id = item.get("diagnosticId")
                      if isinstance(diagnostic_id, str) and diagnostic_id:
                          ids.add(diagnostic_id)
          return ids

      request = read_object(request_path)
      should_create_pr = request.get("shouldCreatePr") is True

      included_task_statuses: dict[str, str] = {}
      merge_report = read_object(merge_report_path)
      groups = merge_report.get("groups")
      for group in groups if isinstance(groups, list) else []:
          if not isinstance(group, dict):
              continue
          patches = group.get("patches")
          for patch in patches if isinstance(patches, list) else []:
              if not isinstance(patch, dict):
                  continue
              task_id = patch.get("taskId")
              status = patch.get("status")
              if isinstance(task_id, str) and isinstance(status, str):
                  included_task_statuses[task_id] = status

      tasks_by_diagnostic: dict[str, dict[str, Any]] = {}
      run_full = read_object(run_full_path)
      task_entries = run_full.get("tasks")
      for entry in task_entries if isinstance(task_entries, list) else []:
          if not isinstance(entry, dict):
              continue
          task = entry.get("task") if isinstance(entry.get("task"), dict) else {}
          result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
          task_id = str(entry.get("taskId") or task.get("id") or result.get("taskId") or "")
          status = str(result.get("status") or "unknown")
          for diagnostic_id in diagnostic_ids_for_task(entry):
              tasks_by_diagnostic[diagnostic_id] = {
                  "taskId": task_id,
                  "remediationStatus": status,
                  "patchStatus": included_task_statuses.get(task_id),
              }

      items = []
      by_diagnostic_id: dict[str, dict[str, Any]] = {}
      for diagnostic in read_items(introduced_path, "introduced_diagnostics"):
          diagnostic_id = diagnostic.get("diagnosticId")
          rule = diagnostic.get("rule")
          task = tasks_by_diagnostic.get(str(diagnostic_id), {}) if isinstance(diagnostic_id, str) else {}
          patch_status = task.get("patchStatus")
          addressed = should_create_pr and patch_status in {"applied", "merged_by_agent"}

          if addressed:
              status = "addressed"
              comment_status = "Addressed in the generated cleanup PR."
          elif task:
              status = "not_addressed"
              comment_status = "Not addressed in the generated cleanup PR."
          else:
              status = "not_addressed"
              comment_status = "Not selected for automatic remediation."

          item = {
              "diagnosticId": diagnostic_id,
              "filePath": diagnostic.get("filePath"),
              "line": diagnostic.get("line"),
              "rule": rule,
              "analysisSource": diagnostic.get("analysisSource"),
              "status": status,
              "commentStatus": comment_status,
              "taskId": task.get("taskId"),
              "remediationStatus": task.get("remediationStatus"),
              "patchStatus": patch_status,
          }
          items.append(item)
          if isinstance(diagnostic_id, str) and diagnostic_id:
              by_diagnostic_id[diagnostic_id] = item

      output = {
          "schemaVersion": "code-quality.remediation-comment-status.v1",
          "shouldCreatePr": should_create_pr,
          "items": items,
          "byDiagnosticId": by_diagnostic_id,
      }
      output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
      PY

  - name: Upload code quality remediation artifacts
    if: always()
    uses: actions/upload-artifact@v7.0.1
    with:
      name: code-quality-pr-agentic-fix-${{ github.run_id }}
      path: |
        /tmp/repo-analysis/
        /tmp/gh-aw/agent/create-pr-request.json
        /tmp/gh-aw/agent/introduced-diagnostics.json
        /tmp/gh-aw/agent/introduced-findings-issue.md
        /tmp/gh-aw/agent/remediation-status.json
      retention-days: 14
      if-no-files-found: warn

  - name: Skip final gh-aw agent phase
    if: always()
    run: |
      set -euo pipefail
      safe_outputs="${RUNNER_TEMP}/gh-aw/safeoutputs/outputs.jsonl"
      mkdir -p "$(dirname "$safe_outputs")"
      printf '{"type":"noop","message":"Code quality reporting and cleanup PR creation are handled by the deterministic publish job."}\n' >> "$safe_outputs"
---

# Code Quality PR Agentic Fix

The deterministic workflow steps already handle scanning, remediation patch
generation, artifact upload, issue reporting, inline comments, cleanup branch
publishing, and cleanup PR creation.

No agent action is required for this workflow.
