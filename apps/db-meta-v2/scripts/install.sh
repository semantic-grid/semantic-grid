#!/bin/sh
# dbmeta installer
# Usage: curl -fsSL https://semantic-grid.io/install.sh | sh
#
# Environment variables:
#   DBMETA_VERSION  - Version to install (default: latest)
#   DBMETA_INSTALL  - Installation directory (default: ~/.local/bin)

set -e

# GitHub repository
REPO="semantic-grid/semantic-grid"

# Color output helpers (POSIX-compatible)
info()    { printf '\033[34m%s\033[0m\n' "$1"; }
success() { printf '\033[32m%s\033[0m\n' "$1"; }
warn()    { printf '\033[33m%s\033[0m\n' "$1"; }
error()   { printf '\033[31m%s\033[0m\n' "$1" >&2; }

# Detect OS and architecture
detect_platform() {
    os=""
    arch=""

    case "$(uname -s)" in
        Darwin)
            os="macos"
            ;;
        Linux)
            os="linux"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            os="windows"
            ;;
        *)
            error "Unsupported operating system: $(uname -s)"
            exit 1
            ;;
    esac

    case "$(uname -m)" in
        x86_64|amd64)
            arch="x64"
            ;;
        arm64|aarch64)
            arch="arm64"
            ;;
        *)
            error "Unsupported architecture: $(uname -m)"
            exit 1
            ;;
    esac

    printf '%s-%s' "$os" "$arch"
}

# Get latest release version from GitHub
get_latest_version() {
    curl -sL "https://api.github.com/repos/${REPO}/releases/latest" | \
        grep '"tag_name":' | \
        sed -E 's/.*"([^"]+)".*/\1/' | \
        sed 's/^dbmeta-v//'
}

# Download binary
download_binary() {
    version="$1"
    platform="$2"
    dest="$3"

    ext=""
    case "$platform" in
        windows-*) ext=".exe" ;;
    esac

    filename="dbmeta-${platform}${ext}"
    url="https://github.com/${REPO}/releases/download/dbmeta-v${version}/${filename}"

    info "Downloading dbmeta v${version} for ${platform}..."
    printf '  URL: %s\n' "$url"

    # On macOS, download to cache dir and symlink to avoid Gatekeeper issues
    case "$platform" in
        macos-*)
            cache_dir="$HOME/.dbmeta/cache"
            mkdir -p "$cache_dir"
            cache_path="${cache_dir}/dbmeta-${version}${ext}"

            if ! curl -fsSL "$url" -o "$cache_path"; then
                error "Failed to download from ${url}"
                exit 1
            fi
            chmod +x "$cache_path"

            # Remove old symlink/file and create new symlink
            rm -f "$dest"
            ln -s "$cache_path" "$dest"
            ;;
        *)
            if ! curl -fsSL "$url" -o "$dest"; then
                error "Failed to download from ${url}"
                exit 1
            fi
            chmod +x "$dest"
            ;;
    esac
}

# Main installation
main() {
    printf '\033[34m'
    printf '╔════════════════════════════════════════╗\n'
    printf '║       dbmeta Installer                 ║\n'
    printf '║  Database MCP Server for Claude        ║\n'
    printf '╚════════════════════════════════════════╝\n'
    printf '\033[0m\n'

    # Detect platform
    platform=$(detect_platform)
    printf 'Platform: \033[32m%s\033[0m\n' "$platform"

    # Get version
    version="${DBMETA_VERSION:-}"
    if [ -z "$version" ]; then
        printf 'Fetching latest version...\n'
        version=$(get_latest_version)
        if [ -z "$version" ]; then
            warn "Could not determine latest version. Using 'latest'."
            version="latest"
        fi
    fi
    printf 'Version: \033[32m%s\033[0m\n' "$version"

    # Determine install directory
    install_dir="${DBMETA_INSTALL:-$HOME/.local/bin}"
    binary_path="${install_dir}/dbmeta"

    # Create install directory
    mkdir -p "$install_dir"

    # Download
    download_binary "$version" "$platform" "$binary_path"

    # Verify installation
    if [ -x "$binary_path" ]; then
        success "✓ dbmeta installed successfully!"
        printf '  Location: %s\n\n' "$binary_path"

        # Check if in PATH
        case ":$PATH:" in
            *":$install_dir:"*) ;;
            *)
                warn "Note: ${install_dir} is not in your PATH."
                printf 'Add this to your shell profile (~/.bashrc, ~/.zshrc, etc.):\n\n'
                printf '  \033[34mexport PATH="$HOME/.local/bin:$PATH"\033[0m\n\n'
                ;;
        esac

        success "Next steps:"
        printf '  1. Run '\''dbmeta init'\'' to configure your database connection\n'
        printf '  2. Restart Claude Desktop and start querying!\n\n'
    else
        error "Installation failed."
        exit 1
    fi
}

main "$@"
