#!/usr/bin/env bash
# Install git hooks for BloombergGPT
# Usage: ./scripts/install-hooks.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "Installing Git hooks..."

# Check if we're in a git repository
if [ ! -d "$HOOKS_DIR" ]; then
    echo "Error: Not in a git repository or .git/hooks directory not found"
    exit 1
fi

# Install pre-commit hook
if [ -f "$HOOKS_DIR/pre-commit" ]; then
    echo -e "${YELLOW}⚠  Pre-commit hook already exists. Creating backup...${NC}"
    cp "$HOOKS_DIR/pre-commit" "$HOOKS_DIR/pre-commit.backup"
fi

cp "$SCRIPT_DIR/pre-commit" "$HOOKS_DIR/pre-commit"
chmod +x "$HOOKS_DIR/pre-commit"

echo -e "${GREEN}✓ Pre-commit hook installed${NC}"
echo ""
echo "The hook will now check for secrets before each commit."
echo ""
echo "To test it, try:"
echo "  echo 'OPENAI_API_KEY=sk-test123456' > test.txt"
echo "  git add test.txt"
echo "  git commit -m 'test' # Should be blocked"
echo ""
echo "To bypass the hook (not recommended):"
echo "  git commit --no-verify"
echo ""
