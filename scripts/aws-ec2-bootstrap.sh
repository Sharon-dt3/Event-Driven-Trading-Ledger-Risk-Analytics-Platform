#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# TradePulse — AWS EC2 Free Tier (t3.micro / 1 GB RAM) bootstrap
#
# Purpose: bring the full TradePulse stack up on a single free-tier EC2 box.
# The stack is memory-heavy (8 containers incl. a Java/Spring build), so 1 GB
# of RAM alone will OOM. This script mitigates that by:
#   1. adding a swapfile (default 4 GB) so the kernel has spillover room, and
#   2. building the Docker images ONE AT A TIME (sequential) instead of the
#      default parallel build, which is what actually blows up a t3.micro.
#
# It is idempotent: safe to re-run. It supports both Amazon Linux 2023 and
# Ubuntu 22.04/24.04.
#
# USAGE
#   As EC2 "user data" (runs as root on first boot):
#     paste this whole file into the instance's User data field.
#
#   Or manually on the box:
#     curl -fsSL <raw-url>/scripts/aws-ec2-bootstrap.sh -o bootstrap.sh
#     sudo bash bootstrap.sh
#
# ENV OVERRIDES (optional, export before running):
#   REPO_URL     git URL to clone (default: the public GitHub repo)
#   REPO_BRANCH  branch to check out (default: main)
#   APP_DIR      where to clone (default: /opt/tradepulse)
#   SWAP_GB      swapfile size in GiB (default: 4)
#   PUBLIC_PORT  host port for the single URL (default: 80)
#   RUN_USER     non-root user to own the checkout (default: auto-detected)
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Sharon-dt3/Event-Driven-Trading-Ledger-Risk-Analytics-Platform.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/tradepulse}"
SWAP_GB="${SWAP_GB:-4}"
PUBLIC_PORT="${PUBLIC_PORT:-80}"

log() { echo -e "\n[bootstrap] $*"; }

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "This script must run as root (use sudo)." >&2
    exit 1
  fi
}

detect_os() {
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_LIKE="${ID_LIKE:-}"
  log "Detected OS: ${PRETTY_NAME:-$OS_ID}"
}

# Pick a sensible non-root user to own the repo checkout.
detect_run_user() {
  if [ -n "${RUN_USER:-}" ]; then return; fi
  if id ec2-user >/dev/null 2>&1; then RUN_USER=ec2-user
  elif id ubuntu >/dev/null 2>&1; then RUN_USER=ubuntu
  else RUN_USER=root
  fi
  log "Repo will be owned by user: $RUN_USER"
}

setup_swap() {
  if swapon --show | grep -q '/swapfile'; then
    log "Swap already configured; skipping."
    return
  fi
  log "Creating ${SWAP_GB}G swapfile at /swapfile ..."
  # fallocate is fast but not supported on all FS; fall back to dd.
  if ! fallocate -l "${SWAP_GB}G" /swapfile 2>/dev/null; then
    dd if=/dev/zero of=/swapfile bs=1M count=$((SWAP_GB * 1024)) status=progress
  fi
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  if ! grep -q '/swapfile' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
  # Reduce swappiness so RAM is preferred but swap is available under pressure.
  sysctl -w vm.swappiness=20 >/dev/null || true
  if ! grep -q 'vm.swappiness' /etc/sysctl.conf; then
    echo 'vm.swappiness=20' >> /etc/sysctl.conf
  fi
  log "Swap enabled:"
  free -h || true
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker + compose plugin already installed; skipping."
    return
  fi
  case "$OS_ID" in
    amzn)
      log "Installing Docker on Amazon Linux ..."
      dnf install -y docker git
      # The compose plugin isn't in the AL2023 docker package; install manually.
      mkdir -p /usr/libexec/docker/cli-plugins
      COMPOSE_VER="v2.29.7"
      ARCH="$(uname -m)"
      curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VER}/docker-compose-linux-${ARCH}" \
        -o /usr/libexec/docker/cli-plugins/docker-compose
      chmod +x /usr/libexec/docker/cli-plugins/docker-compose
      ;;
    ubuntu|debian)
      log "Installing Docker on Ubuntu/Debian ..."
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -y
      apt-get install -y ca-certificates curl git gnupg
      install -m 0755 -d /etc/apt/keyrings
      curl -fsSL "https://download.docker.com/linux/${OS_ID}/gpg" -o /etc/apt/keyrings/docker.asc
      chmod a+r /etc/apt/keyrings/docker.asc
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${OS_ID} $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
      apt-get update -y
      apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
      ;;
    *)
      echo "Unsupported OS '$OS_ID'. Install Docker + compose plugin manually, then re-run." >&2
      exit 1
      ;;
  esac
  systemctl enable --now docker
  if [ "$RUN_USER" != "root" ]; then
    usermod -aG docker "$RUN_USER" || true
  fi
  log "Docker installed:"
  docker --version || true
  docker compose version || true
}

clone_repo() {
  if [ -d "$APP_DIR/.git" ]; then
    log "Repo already present at $APP_DIR; pulling latest ..."
    git -C "$APP_DIR" fetch --all --prune
    git -C "$APP_DIR" checkout "$REPO_BRANCH"
    git -C "$APP_DIR" pull --ff-only origin "$REPO_BRANCH" || true
  else
    log "Cloning $REPO_URL ($REPO_BRANCH) into $APP_DIR ..."
    mkdir -p "$APP_DIR"
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$APP_DIR"
  fi
  chown -R "$RUN_USER":"$RUN_USER" "$APP_DIR" 2>/dev/null || true
}

# Generate infra/.env with strong secrets so the public-facing app isn't left
# on the in-repo demo credentials. Only created if it doesn't already exist.
generate_env() {
  local env_file="$APP_DIR/infra/.env"
  if [ -f "$env_file" ]; then
    log "infra/.env already exists; leaving it untouched."
    return
  fi
  log "Generating infra/.env with strong random secrets ..."
  local jwt admin trader viewer compliance pg
  jwt="$(openssl rand -base64 48 | tr -d '\n')"
  admin="$(openssl rand -base64 18 | tr -d '\n')"
  trader="$(openssl rand -base64 18 | tr -d '\n')"
  viewer="$(openssl rand -base64 18 | tr -d '\n')"
  compliance="$(openssl rand -base64 18 | tr -d '\n')"
  pg="$(openssl rand -base64 24 | tr -d '\n')"
  cat > "$env_file" <<EOF
# Auto-generated by aws-ec2-bootstrap.sh — keep this file secret (it is gitignored).
# The four login usernames remain: admin / demo_trader / viewer / compliance.
PUBLIC_PORT=${PUBLIC_PORT}
POSTGRES_PASSWORD=${pg}
LEDGER_JWT_SECRET=${jwt}
LEDGER_AUTH_ADMIN_PASSWORD=${admin}
LEDGER_AUTH_TRADER_PASSWORD=${trader}
LEDGER_AUTH_VIEWER_PASSWORD=${viewer}
LEDGER_AUTH_COMPLIANCE_PASSWORD=${compliance}
EOF
  chmod 600 "$env_file"
  chown "$RUN_USER":"$RUN_USER" "$env_file" 2>/dev/null || true
  log "Wrote $env_file. Your generated login passwords:"
  echo "    admin        : ${admin}"
  echo "    demo_trader  : ${trader}"
  echo "    viewer       : ${viewer}"
  echo "    compliance   : ${compliance}"
  echo "  (Also saved above in infra/.env. Store them somewhere safe.)"
}

# Build images sequentially to keep peak RAM low. The default parallel build
# is the main reason the stack OOMs on a 1 GB instance.
build_and_up() {
  local compose="docker compose -f infra/docker-compose.deploy.yml"
  cd "$APP_DIR"
  export COMPOSE_PROJECT_NAME=tradepulse
  export DOCKER_BUILDKIT=1

  log "Building images sequentially (this is slow on t3.micro but avoids OOM) ..."
  for svc in market-data gateway risk-engine dashboard ledger-core; do
    log "  building $svc ..."
    # --memory limits the build container; leave headroom for the daemon+swap.
    $compose build "$svc"
  done

  log "Starting the stack (detached) ..."
  PUBLIC_PORT="$PUBLIC_PORT" $compose up -d

  log "Containers:"
  $compose ps || true
}

main() {
  require_root
  detect_os
  detect_run_user
  setup_swap
  install_docker
  clone_repo
  generate_env
  build_and_up
  local ip
  ip="$(curl -fsSL http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo '<EC2-PUBLIC-IP>')"
  log "Done. Once healthy (give the Java service ~1-2 min), open:  http://${ip}:${PUBLIC_PORT}/"
  log "Watch progress with:  cd ${APP_DIR} && docker compose -f infra/docker-compose.deploy.yml logs -f"
}

main "$@"
