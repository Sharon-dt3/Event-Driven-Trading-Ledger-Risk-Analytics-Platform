#!/usr/bin/env bash
#
# verify-native.sh — Verify each TradePulse service builds and tests WITHOUT Docker.
#
# Why this exists:
#   In restricted/nested-container environments the Docker daemon cannot extract
#   image layers ("failed to register layer: unshare: operation not permitted"),
#   so `make up` cannot run. This script proves that each service compiles, its
#   dependencies resolve, and its unit tests pass using the native toolchains
#   instead — the real "is it all installed / wired correctly" check.
#
# Symlink-averse filesystems:
#   Some virtualized workspace mounts allow regular file writes but reject symlink
#   creation (EROFS on symlink). That breaks `python -m venv` (creates lib64->lib)
#   and `npm install` (creates node_modules/.bin/* symlinks). To stay robust, the
#   Python and Node steps run in a temporary directory (typically a tmpfs under
#   $TMPDIR//tmp) that supports symlinks, rather than under the workspace mount.
#   This approach is verified working: risk-engine pytest passes and the dashboard
#   Vite build succeeds when run from $TMPDIR.
#
# Behavior:
#   - Each service is verified independently.
#   - If a service's toolchain is not installed, that service is SKIPPED (not failed),
#     unless STRICT=1 is set (then a missing toolchain counts as a failure).
#   - Any real build/test failure marks the service FAILED.
#   - A summary table is printed at the end; exit code is non-zero if anything FAILED.
#
# Usage:
#   ./scripts/verify-native.sh            # skip services with missing toolchains
#   STRICT=1 ./scripts/verify-native.sh   # missing toolchain => failure
#
set -uo pipefail

# Resolve repo root as the parent of this script's directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICES_DIR="${ROOT_DIR}/services"

STRICT="${STRICT:-0}"
TMP_BASE="${TMPDIR:-/tmp}"

# Result tracking (parallel arrays; keeps compatibility with older bash).
RESULT_NAMES=()
RESULT_STATES=()
RESULT_NOTES=()

# Colors (disabled when not a TTY).
if [ -t 1 ]; then
  C_RESET="\033[0m"; C_GREEN="\033[32m"; C_RED="\033[31m"; C_YELLOW="\033[33m"; C_BOLD="\033[1m"
else
  C_RESET=""; C_GREEN=""; C_RED=""; C_YELLOW=""; C_BOLD=""
fi

log()  { printf '%b\n' "$*"; }
hdr()  { printf '\n%b\n' "${C_BOLD}==> $*${C_RESET}"; }

record() {
  # record <name> <PASS|SKIP|FAIL> <note>
  RESULT_NAMES+=("$1")
  RESULT_STATES+=("$2")
  RESULT_NOTES+=("$3")
}

have() { command -v "$1" >/dev/null 2>&1; }

# Handle a missing toolchain consistently (respects STRICT).
missing_tool() {
  # missing_tool <service> <toolname>
  local svc="$1" tool="$2"
  if [ "${STRICT}" = "1" ]; then
    log "${C_RED}${tool} not found — STRICT mode: marking ${svc} as FAILED${C_RESET}"
    record "${svc}" "FAIL" "missing toolchain: ${tool}"
    return 1
  else
    log "${C_YELLOW}${tool} not found — skipping ${svc}${C_RESET}"
    record "${svc}" "SKIP" "missing toolchain: ${tool}"
    return 1
  fi
}

# ---------------------------------------------------------------------------
# Go services: build + vet + test
# ---------------------------------------------------------------------------
verify_go_service() {
  local svc="$1"
  local dir="${SERVICES_DIR}/${svc}"
  hdr "Go service: ${svc}"

  if [ ! -d "${dir}" ]; then
    log "${C_YELLOW}Directory ${dir} not found — skipping${C_RESET}"
    record "${svc}" "SKIP" "directory missing"
    return
  fi
  if ! have go; then
    missing_tool "${svc}" "go" || return
  fi

  (
    cd "${dir}" || exit 3
    log "go version: $(go version)"
    log "-> go build ./..."
    go build ./... || exit 1
    log "-> go vet ./..."
    go vet ./... || exit 1
    log "-> go test ./..."
    go test ./... || exit 1
  )
  local rc=$?
  if [ "${rc}" -eq 0 ]; then
    log "${C_GREEN}${svc}: build + vet + test OK${C_RESET}"
    record "${svc}" "PASS" "go build/vet/test"
  else
    log "${C_RED}${svc}: FAILED (rc=${rc})${C_RESET}"
    record "${svc}" "FAIL" "go build/vet/test (rc=${rc})"
  fi
}

# ---------------------------------------------------------------------------
# Python service (risk-engine): venv (in tmpfs) + deps + pytest
#
# The venv is created under ${TMP_BASE} because the workspace mount may reject
# the lib64 -> lib symlink that `python -m venv` creates. Using --copies avoids
# symlinks entirely. Tests still run from the service directory so imports
# resolve against the real sources.
# ---------------------------------------------------------------------------
verify_python_service() {
  local svc="risk-engine"
  local dir="${SERVICES_DIR}/${svc}"
  hdr "Python service: ${svc}"

  if [ ! -d "${dir}" ]; then
    log "${C_YELLOW}Directory ${dir} not found — skipping${C_RESET}"
    record "${svc}" "SKIP" "directory missing"
    return
  fi

  local PY=""
  if have python3; then PY="python3"; elif have python; then PY="python"; fi
  if [ -z "${PY}" ]; then
    missing_tool "${svc}" "python3" || return
  fi

  local tmp_root
  tmp_root="$(mktemp -d "${TMP_BASE}/tp-verify-${svc}.XXXXXX" 2>/dev/null)" || {
    log "${C_RED}Could not create temp dir under ${TMP_BASE}${C_RESET}"
    record "${svc}" "FAIL" "cannot create temp dir"
    return
  }

  (
    cd "${dir}" || exit 3
    log "python version: $(${PY} --version 2>&1)"
    local VENV="${tmp_root}/venv"
    log "-> creating virtualenv (in ${TMP_BASE}) with --copies"
    ${PY} -m venv --copies "${VENV}" || exit 1
    # shellcheck disable=SC1091
    . "${VENV}/bin/activate" || exit 1
    log "-> upgrading pip"
    python -m pip install --quiet --upgrade pip || exit 1
    log "-> installing dev requirements"
    if [ -f requirements-dev.txt ]; then
      python -m pip install --quiet -r requirements-dev.txt || exit 1
    elif [ -f requirements.txt ]; then
      python -m pip install --quiet -r requirements.txt || exit 1
    fi
    log "-> pytest"
    python -m pytest -q || exit 1
  )
  local rc=$?
  rm -rf "${tmp_root}" 2>/dev/null || true
  if [ "${rc}" -eq 0 ]; then
    log "${C_GREEN}${svc}: deps + pytest OK${C_RESET}"
    record "${svc}" "PASS" "venv(tmpfs) + pytest"
  else
    log "${C_RED}${svc}: FAILED (rc=${rc})${C_RESET}"
    record "${svc}" "FAIL" "venv + pytest (rc=${rc})"
  fi
}

# ---------------------------------------------------------------------------
# Java service (ledger-core): Maven verify
#
# `mvn verify` runs the full default suite on H2 (no Docker/Redis), which now
# includes the Phase 5 duplicate-delivery idempotency guard
# (Phase5PocConsumerPollDedupeTest). The REDIS_IT-gated live-Redis tests and the
# poc/native-kill-restart proof are the deeper, broker-backed checks.
# ---------------------------------------------------------------------------
verify_java_service() {
  local svc="ledger-core"
  local dir="${SERVICES_DIR}/${svc}"
  hdr "Java service: ${svc}"

  if [ ! -d "${dir}" ]; then
    log "${C_YELLOW}Directory ${dir} not found — skipping${C_RESET}"
    record "${svc}" "SKIP" "directory missing"
    return
  fi

  local MVN=""
  if [ -x "${dir}/mvnw" ]; then
    MVN="./mvnw"
  elif have mvn; then
    MVN="mvn"
  else
    missing_tool "${svc}" "mvn (or ./mvnw)" || return
  fi
  if ! have java; then
    missing_tool "${svc}" "java" || return
  fi

  (
    cd "${dir}" || exit 3
    log "java version: $(java -version 2>&1 | head -1)"
    log "-> ${MVN} -B -q verify"
    ${MVN} -B -q verify || exit 1
  )
  local rc=$?
  if [ "${rc}" -eq 0 ]; then
    log "${C_GREEN}${svc}: maven verify OK${C_RESET}"
    record "${svc}" "PASS" "mvn verify"
  else
    log "${C_RED}${svc}: FAILED (rc=${rc})${C_RESET}"
    record "${svc}" "FAIL" "mvn verify (rc=${rc})"
  fi
}

# ---------------------------------------------------------------------------
# Node service (dashboard): npm install + build (+ lint), run in a tmpfs copy
#
# npm creates node_modules/.bin/* symlinks, which the workspace mount may reject.
# To stay robust we copy the service sources (excluding node_modules/dist) into a
# temp dir under ${TMP_BASE} and build there.
# ---------------------------------------------------------------------------
verify_node_service() {
  local svc="dashboard"
  local dir="${SERVICES_DIR}/${svc}"
  hdr "Node service: ${svc}"

  if [ ! -d "${dir}" ]; then
    log "${C_YELLOW}Directory ${dir} not found — skipping${C_RESET}"
    record "${svc}" "SKIP" "directory missing"
    return
  fi
  if ! have npm; then
    missing_tool "${svc}" "npm" || return
  fi

  local tmp_root
  tmp_root="$(mktemp -d "${TMP_BASE}/tp-verify-${svc}.XXXXXX" 2>/dev/null)" || {
    log "${C_RED}Could not create temp dir under ${TMP_BASE}${C_RESET}"
    record "${svc}" "FAIL" "cannot create temp dir"
    return
  }
  local work="${tmp_root}/${svc}"
  mkdir -p "${work}"

  log "-> copying sources to ${work} (excluding node_modules, dist)"
  if ! tar -cf - --exclude=./node_modules --exclude=./dist -C "${dir}" . 2>/dev/null | tar -xf - -C "${work}"; then
    log "${C_RED}Failed to copy sources to temp dir${C_RESET}"
    rm -rf "${tmp_root}" 2>/dev/null || true
    record "${svc}" "FAIL" "source copy to temp failed"
    return
  fi

  (
    cd "${work}" || exit 3
    log "node version: $(node --version 2>&1)"
    log "npm version: $(npm --version 2>&1)"
    if [ -f package-lock.json ]; then
      log "-> npm ci"
      npm ci || exit 1
    else
      log "-> npm install (no package-lock.json present)"
      npm install || exit 1
    fi
    log "-> npm run build"
    npm run build || exit 1
    if npm run 2>/dev/null | grep -q '^  lint'; then
      log "-> npm run lint"
      npm run lint || exit 1
    fi
  )
  local rc=$?
  rm -rf "${tmp_root}" 2>/dev/null || true
  if [ "${rc}" -eq 0 ]; then
    log "${C_GREEN}${svc}: install + build OK${C_RESET}"
    record "${svc}" "PASS" "npm install/build (tmpfs)"
  else
    log "${C_RED}${svc}: FAILED (rc=${rc})${C_RESET}"
    record "${svc}" "FAIL" "npm install/build (rc=${rc})"
  fi
}

# ---------------------------------------------------------------------------
# Contracts gate (Phase 0): validate sample payloads against their JSON Schemas.
#
# Offline & hermetic: reads only local files under docs/contracts/. It prefers
# the already-installed interpreter when jsonschema + referencing are importable
# (no network). If they are missing, it attempts a one-off install of the PINNED
# versions into a tmpfs venv; if that can't happen (e.g. no network), the step is
# SKIPPED (or FAILED under STRICT), consistent with the rest of this script.
# ---------------------------------------------------------------------------
verify_contracts() {
  local name="contracts"
  local script="${ROOT_DIR}/utils/validate_contracts.py"
  local reqs="${ROOT_DIR}/docs/contracts/requirements.txt"
  hdr "Contracts gate: ${name}"

  if [ ! -f "${script}" ]; then
    log "${C_YELLOW}${script} not found — skipping${C_RESET}"
    record "${name}" "SKIP" "validator script missing"
    return
  fi

  local PY=""
  if have python3; then PY="python3"; elif have python; then PY="python"; fi
  if [ -z "${PY}" ]; then
    missing_tool "${name}" "python3" || return
  fi

  # Fast path: deps already importable -> run directly, fully offline.
  if ${PY} -c "import jsonschema, referencing" >/dev/null 2>&1; then
    log "-> using preinstalled jsonschema + referencing (offline)"
    if ${PY} "${script}"; then
      log "${C_GREEN}${name}: all samples valid${C_RESET}"
      record "${name}" "PASS" "validate_contracts.py (preinstalled deps)"
    else
      log "${C_RED}${name}: FAILED${C_RESET}"
      record "${name}" "FAIL" "validate_contracts.py"
    fi
    return
  fi

  # Fallback: install pinned deps into a tmpfs venv (may need network).
  log "${C_YELLOW}jsonschema/referencing not importable — attempting pinned install${C_RESET}"
  local tmp_root
  tmp_root="$(mktemp -d "${TMP_BASE}/tp-verify-${name}.XXXXXX" 2>/dev/null)" || {
    log "${C_RED}Could not create temp dir under ${TMP_BASE}${C_RESET}"
    record "${name}" "SKIP" "cannot create temp dir for deps"
    return
  }
  local rc=0
  (
    VENV="${tmp_root}/venv"
    ${PY} -m venv --copies "${VENV}" || exit 3
    # shellcheck disable=SC1091
    . "${VENV}/bin/activate" || exit 3
    python -m pip install --quiet --upgrade pip || exit 3
    if [ -f "${reqs}" ]; then
      python -m pip install --quiet -r "${reqs}" || exit 3
    else
      python -m pip install --quiet "jsonschema==4.23.0" "referencing==0.36.2" || exit 3
    fi
    python "${script}" || exit 1
  )
  rc=$?
  rm -rf "${tmp_root}" 2>/dev/null || true
  case "${rc}" in
    0) log "${C_GREEN}${name}: all samples valid${C_RESET}"
       record "${name}" "PASS" "validate_contracts.py (pinned venv)";;
    1) log "${C_RED}${name}: FAILED (schema validation)${C_RESET}"
       record "${name}" "FAIL" "validate_contracts.py (validation)";;
    *) # Could not set up deps (e.g. offline). Treat like a missing toolchain.
       if [ "${STRICT}" = "1" ]; then
         log "${C_RED}${name}: could not install deps — STRICT: FAILED${C_RESET}"
         record "${name}" "FAIL" "cannot install pinned deps"
       else
         log "${C_YELLOW}${name}: could not install deps — skipping${C_RESET}"
         record "${name}" "SKIP" "cannot install pinned deps (offline?)"
       fi;;
  esac
}

# ---------------------------------------------------------------------------
# Run all verifications
# ---------------------------------------------------------------------------
main() {
  hdr "TradePulse native verification (no Docker required)"
  log "Repo root: ${ROOT_DIR}"
  log "Temp base: ${TMP_BASE} (used for symlink-averse steps)"
  log "STRICT mode: ${STRICT} (1 = missing toolchain is a failure)"

  verify_go_service "market-data"
  verify_go_service "gateway"
  verify_python_service
  verify_java_service
  verify_node_service
  verify_contracts

  # -------- Summary --------
  hdr "Summary"
  local pass=0 skip=0 fail=0
  local i
  for i in "${!RESULT_NAMES[@]}"; do
    local name="${RESULT_NAMES[$i]}"
    local state="${RESULT_STATES[$i]}"
    local note="${RESULT_NOTES[$i]}"
    local color="${C_RESET}"
    case "${state}" in
      PASS) color="${C_GREEN}"; pass=$((pass+1));;
      SKIP) color="${C_YELLOW}"; skip=$((skip+1));;
      FAIL) color="${C_RED}"; fail=$((fail+1));;
    esac
    printf '%b  %-14s %-5s%b  %s\n' "${color}" "${name}" "${state}" "${C_RESET}" "${note}"
  done

  printf '\n%bTotals:%b PASS=%d SKIP=%d FAIL=%d\n' "${C_BOLD}" "${C_RESET}" "${pass}" "${skip}" "${fail}"

  if [ "${fail}" -gt 0 ]; then
    log "${C_RED}Native verification FAILED.${C_RESET}"
    return 1
  fi
  log "${C_GREEN}Native verification passed (failures: 0).${C_RESET}"
  if [ "${skip}" -gt 0 ]; then
    log "${C_YELLOW}Note: ${skip} service(s) were skipped due to missing toolchains. Re-run with STRICT=1 to enforce.${C_RESET}"
  fi
  return 0
}

main "$@"
