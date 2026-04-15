#!/usr/bin/env bash
# OpenVegas CLI — God Command Installer
# Hosted at: https://app.openvegas.ai/install
#
# Usage:
#   curl -fsSL https://app.openvegas.ai/install | bash
#   bash <(curl -fsSL https://app.openvegas.ai/install)
#
# What this does:
#   1. Detects OS + architecture
#   2. Installs Bun if not present
#   3. Downloads the correct OpenVegas binary from GitHub Releases
#   4. Installs to ~/.local/bin/openvegas (or /usr/local/bin with sudo)
#   5. Runs `openvegas login` (opens browser → OAuth → saves JWT)
#
# Supported: macOS (arm64, x64), Linux (arm64, x64)
# Windows:   WSL2 is supported; native Windows users: see docs.

set -euo pipefail

# ─── Styling ──────────────────────────────────────────────────────────────────

BOLD="\033[1m"
DIM="\033[2m"
GREEN="\033[32m"
CYAN="\033[36m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

OK="${GREEN}✓${RESET}"
WARN="${YELLOW}!${RESET}"
ERR="${RED}✗${RESET}"

say()   { printf "  %b\n" "$*"; }
step()  { printf "\n${BOLD}${CYAN}→ %s${RESET}\n" "$*"; }
ok()    { printf "  ${OK} %b\n" "$*"; }
warn()  { printf "  ${WARN} ${YELLOW}%b${RESET}\n" "$*"; }
die()   { printf "\n  ${ERR} ${RED}%b${RESET}\n\n" "$*"; exit 1; }

# ─── Constants ────────────────────────────────────────────────────────────────

OPENVEGAS_VERSION="${OPENVEGAS_VERSION:-latest}"
GITHUB_REPO="openvegas/openvegas"
RELEASES_BASE="https://github.com/${GITHUB_REPO}/releases"
INSTALL_DIR="${OPENVEGAS_INSTALL_DIR:-$HOME/.local/bin}"
BIN_NAME="openvegas"
CONFIG_DIR="$HOME/.openvegas"

# ─── OS / Arch detection ──────────────────────────────────────────────────────

detect_platform() {
    local os arch

    case "$(uname -s)" in
        Darwin) os="darwin" ;;
        Linux)  os="linux"  ;;
        MINGW*|CYGWIN*|MSYS*)
            die "Native Windows is not supported. Please use WSL2.\nSee: https://app.openvegas.ai/docs/install#windows"
            ;;
        *) die "Unsupported OS: $(uname -s)" ;;
    esac

    case "$(uname -m)" in
        x86_64|amd64)   arch="x64"   ;;
        arm64|aarch64)  arch="arm64" ;;
        *) die "Unsupported architecture: $(uname -m)" ;;
    esac

    echo "${os}-${arch}"
}

# ─── Dependency checks ────────────────────────────────────────────────────────

check_deps() {
    for cmd in curl tar; do
        if ! command -v "$cmd" &>/dev/null; then
            die "Required command not found: ${cmd}. Please install it and retry."
        fi
    done
}

# ─── Bun install ──────────────────────────────────────────────────────────────

ensure_bun() {
    if command -v bun &>/dev/null; then
        local ver
        ver=$(bun --version 2>/dev/null || echo "unknown")
        ok "Bun already installed (${DIM}${ver}${RESET})"
        return 0
    fi

    step "Installing Bun JavaScript runtime"
    say "${DIM}Downloading from bun.sh/install...${RESET}"

    if curl -fsSL https://bun.sh/install | bash; then
        # Source bun env so subsequent commands can find it
        export BUN_INSTALL="$HOME/.bun"
        export PATH="$BUN_INSTALL/bin:$PATH"
        ok "Bun installed successfully"
    else
        die "Bun installation failed. Install manually: https://bun.sh"
    fi
}

# ─── Resolve binary download URL ──────────────────────────────────────────────

resolve_download_url() {
    local platform="$1"
    local version="$2"

    # Map platform → binary suffix
    # darwin-arm64  → openvegas-darwin-arm64
    # darwin-x64    → openvegas-darwin-x64
    # linux-arm64   → openvegas-linux-arm64
    # linux-x64     → openvegas-linux-x64
    local asset_name="openvegas-${platform}"

    if [ "$version" = "latest" ]; then
        # Resolve actual latest tag via GitHub API (no auth required for public repos)
        local latest_url="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"
        local tag
        tag=$(curl -fsSL "$latest_url" 2>/dev/null \
            | grep '"tag_name"' \
            | head -1 \
            | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')
        if [ -z "$tag" ]; then
            warn "Could not resolve latest version; falling back to /latest redirect"
            echo "${RELEASES_BASE}/latest/download/${asset_name}"
            return
        fi
        echo "${RELEASES_BASE}/download/${tag}/${asset_name}"
    else
        echo "${RELEASES_BASE}/download/${version}/${asset_name}"
    fi
}

# ─── Download & install binary ────────────────────────────────────────────────

install_binary() {
    local platform="$1"
    local url
    url=$(resolve_download_url "$platform" "$OPENVEGAS_VERSION")

    step "Downloading OpenVegas CLI  ${DIM}(${platform})${RESET}"
    say "${DIM}${url}${RESET}"

    # Create install dir
    mkdir -p "$INSTALL_DIR"

    local tmp_bin
    tmp_bin="$(mktemp)"
    trap 'rm -f "$tmp_bin"' EXIT

    if ! curl -fsSL --progress-bar -o "$tmp_bin" "$url"; then
        die "Download failed. Check your internet connection or visit:\n  ${RELEASES_BASE}"
    fi

    chmod +x "$tmp_bin"

    # Smoke-test: make sure it runs
    if ! "$tmp_bin" --version &>/dev/null; then
        die "Downloaded binary failed smoke test. It may not be compatible with this OS.\nPlatform detected: ${platform}"
    fi

    mv "$tmp_bin" "${INSTALL_DIR}/${BIN_NAME}"
    trap - EXIT
    ok "Binary installed to ${INSTALL_DIR}/${BIN_NAME}"
}

# ─── PATH setup ───────────────────────────────────────────────────────────────

ensure_path() {
    # Already on PATH
    if command -v openvegas &>/dev/null; then
        return 0
    fi

    local shell_rc=""
    case "$SHELL" in
        */zsh)  shell_rc="$HOME/.zshrc"    ;;
        */fish) shell_rc="$HOME/.config/fish/config.fish" ;;
        *)      shell_rc="$HOME/.bashrc"   ;;
    esac

    local path_snippet='export PATH="$HOME/.local/bin:$PATH"'
    if [[ "$SHELL" == */fish ]]; then
        path_snippet="fish_add_path \$HOME/.local/bin"
    fi

    if [ -f "$shell_rc" ] && ! grep -q '\.local/bin' "$shell_rc" 2>/dev/null; then
        echo "" >> "$shell_rc"
        echo "# OpenVegas CLI" >> "$shell_rc"
        echo "$path_snippet" >> "$shell_rc"
        warn "Added ~/.local/bin to PATH in ${shell_rc}"
        warn "Run: ${BOLD}source ${shell_rc}${RESET}${YELLOW} or open a new terminal"
    fi

    # Export for the current script session
    export PATH="$INSTALL_DIR:$PATH"
}

# ─── Config dir setup ─────────────────────────────────────────────────────────

setup_config_dir() {
    mkdir -p "${CONFIG_DIR}/ipc/sessions"
    mkdir -p "${CONFIG_DIR}/keys"
    chmod 700 "${CONFIG_DIR}"
    chmod 700 "${CONFIG_DIR}/keys"
}

# ─── Main ────────────────────────────────────────────────────────────────────

main() {
    printf "\n${BOLD}${CYAN}   OpenVegas CLI Installer${RESET}\n"
    printf "   ${DIM}Terminal Arcade for Developers${RESET}\n\n"

    check_deps
    local platform
    platform=$(detect_platform)
    ok "Platform: ${BOLD}${platform}${RESET}"

    ensure_bun
    install_binary "$platform"
    ensure_path
    setup_config_dir

    printf "\n${BOLD}${GREEN}  Installation complete!${RESET}\n\n"
    say "  Run ${BOLD}openvegas login${RESET} to authenticate via browser"
    say "  Run ${BOLD}openvegas chat${RESET} to start your first session"
    say ""
    say "  ${DIM}Docs: https://app.openvegas.ai/docs${RESET}"
    printf "\n"

    # Kick off login if terminal is interactive and not CI
    if [ -t 0 ] && [ "${CI:-}" = "" ] && [ "${OPENVEGAS_SKIP_LOGIN:-}" = "" ]; then
        printf "  ${CYAN}Starting login...${RESET}\n\n"
        exec "${INSTALL_DIR}/${BIN_NAME}" login
    fi
}

main "$@"
