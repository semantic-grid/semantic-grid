#!/usr/bin/env bash
# dbmeta installer
# Usage: curl -fsSL https://semantic-grid.io/install.sh | bash
#
# Environment variables:
#   DBMETA_VERSION  - Version to install (default: latest)
#   DBMETA_INSTALL  - Installation directory (default: ~/.local/bin)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# GitHub repository
REPO="semantic-grid/semantic-grid"

# Detect OS and architecture
detect_platform() {
    local os arch

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
            echo -e "${RED}Unsupported operating system: $(uname -s)${NC}"
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
            echo -e "${RED}Unsupported architecture: $(uname -m)${NC}"
            exit 1
            ;;
    esac

    echo "${os}-${arch}"
}

# Get latest release version from GitHub
get_latest_version() {
    curl -sL "https://api.github.com/repos/${REPO}/releases/latest" | \
        grep '"tag_name":' | \
        sed -E 's/.*"([^"]+)".*/\1/' | \
        sed 's/^dbmeta-//'
}

# Download binary
download_binary() {
    local version="$1"
    local platform="$2"
    local dest="$3"

    local ext=""
    if [[ "$platform" == windows-* ]]; then
        ext=".exe"
    fi

    local filename="dbmeta-${platform}${ext}"
    # Use v2 branch for testing
    local url="https://github.com/${REPO}/releases/download/dbmeta-v${version}/${filename}"
    # Note: install script URL uses v2 branch:
    # https://raw.githubusercontent.com/semantic-grid/semantic-grid/v2/apps/db-meta-v2/scripts/install.sh

    echo -e "${BLUE}Downloading dbmeta v${version} for ${platform}...${NC}"
    echo "  URL: ${url}"

    if ! curl -fsSL "$url" -o "$dest"; then
        echo -e "${RED}Failed to download from ${url}${NC}"
        exit 1
    fi

    chmod +x "$dest"
}

# Main installation
main() {
    echo -e "${BLUE}"
    echo "╔════════════════════════════════════════╗"
    echo "║       dbmeta Installer                 ║"
    echo "║  Database MCP Server for Claude        ║"
    echo "╚════════════════════════════════════════╝"
    echo -e "${NC}"

    # Detect platform
    local platform
    platform=$(detect_platform)
    echo -e "Platform: ${GREEN}${platform}${NC}"

    # Get version
    local version="${DBMETA_VERSION:-}"
    if [[ -z "$version" ]]; then
        echo "Fetching latest version..."
        version=$(get_latest_version)
        if [[ -z "$version" ]]; then
            echo -e "${YELLOW}Could not determine latest version. Using 'latest'.${NC}"
            version="latest"
        fi
    fi
    echo -e "Version: ${GREEN}${version}${NC}"

    # Determine install directory
    local install_dir="${DBMETA_INSTALL:-$HOME/.local/bin}"
    local binary_path="${install_dir}/dbmeta"

    # Create install directory
    mkdir -p "$install_dir"

    # Download
    download_binary "$version" "$platform" "$binary_path"

    # Verify installation
    if [[ -x "$binary_path" ]]; then
        echo -e "${GREEN}✓ dbmeta installed successfully!${NC}"
        echo "  Location: ${binary_path}"
        echo ""

        # Check if in PATH
        if [[ ":$PATH:" != *":$install_dir:"* ]]; then
            echo -e "${YELLOW}Note: ${install_dir} is not in your PATH.${NC}"
            echo "Add this to your shell profile (~/.bashrc, ~/.zshrc, etc.):"
            echo ""
            echo -e "  ${BLUE}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
            echo ""
        fi

        echo -e "${GREEN}Next steps:${NC}"
        echo "  1. Run 'dbmeta init' to configure your database connection"
        echo "  2. Run 'dbmeta claude-desktop' to set up Claude Desktop integration"
        echo "  3. Restart Claude Desktop and start querying!"
        echo ""
    else
        echo -e "${RED}Installation failed.${NC}"
        exit 1
    fi
}

main "$@"
