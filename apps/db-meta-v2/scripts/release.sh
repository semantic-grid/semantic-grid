#!/bin/bash
# Release script for dbmeta CLI
# Usage: ./scripts/release.sh [version]
#
# Examples:
#   ./scripts/release.sh 0.1.0    # Release v0.1.0
#   ./scripts/release.sh          # Prompts for version

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

cd "$APP_DIR"

# Get current version from pyproject.toml
current_version=$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
echo -e "${BLUE}Current version: ${current_version}${NC}"

# Get new version
if [[ -n "$1" ]]; then
    new_version="$1"
else
    echo -n "Enter new version: "
    read new_version
fi

if [[ -z "$new_version" ]]; then
    echo -e "${RED}Version is required${NC}"
    exit 1
fi

# Validate semver format
if ! [[ "$new_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo -e "${RED}Invalid version format. Use semver (e.g., 0.1.0)${NC}"
    exit 1
fi

echo -e "${BLUE}Releasing version: ${new_version}${NC}"
echo ""

# Check for uncommitted changes
if [[ -n $(git status --porcelain) ]]; then
    echo -e "${YELLOW}Warning: You have uncommitted changes${NC}"
    git status --short
    echo ""
    echo -n "Continue anyway? [y/N] "
    read confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# Update version in pyproject.toml
echo -e "${BLUE}Updating pyproject.toml...${NC}"
sed -i '' "s/^version = \".*\"/version = \"${new_version}\"/" pyproject.toml

# Update version in cli.py
echo -e "${BLUE}Updating cli.py...${NC}"
sed -i '' "s/@click.version_option(version=\".*\"/@click.version_option(version=\"${new_version}\"/" src/db_meta_v2/cli.py

# Commit changes
echo -e "${BLUE}Committing version bump...${NC}"
git add pyproject.toml src/db_meta_v2/cli.py
git commit -m "chore: bump dbmeta version to ${new_version}"

# Create tag
tag_name="dbmeta-v${new_version}"
echo -e "${BLUE}Creating tag: ${tag_name}${NC}"
git tag -a "$tag_name" -m "dbmeta v${new_version}"

# Push
echo ""
echo -e "${YELLOW}Ready to push. This will trigger the release workflow.${NC}"
echo -n "Push to origin? [y/N] "
read confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo -e "${YELLOW}Tag created locally but not pushed.${NC}"
    echo "To push later: git push origin main && git push origin ${tag_name}"
    exit 0
fi

echo -e "${BLUE}Pushing to origin...${NC}"
git push origin HEAD
git push origin "$tag_name"

current_branch=$(git rev-parse --abbrev-ref HEAD)

echo ""
echo -e "${GREEN}✓ Release ${new_version} triggered!${NC}"
echo ""
echo "GitHub Actions will now build binaries for all platforms."
echo "Check progress at: https://github.com/semantic-grid/semantic-grid/actions"
echo ""
echo "Once complete, users can install with:"
echo -e "  ${BLUE}curl -fsSL https://raw.githubusercontent.com/semantic-grid/semantic-grid/${current_branch}/apps/db-meta-v2/scripts/install.sh | sh${NC}"
