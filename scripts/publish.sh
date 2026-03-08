#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/publish.sh <version>         # upload to PyPI
#   ./scripts/publish.sh <version> --test  # upload to TestPyPI
#
# Example:
#   ./scripts/publish.sh 0.1.2
#   ./scripts/publish.sh 0.1.2 --test

VERSION="${1:-}"
FLAG="${2:-}"

if [[ -z "$VERSION" ]]; then
  CURRENT=$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
  IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"
  PATCH=$((PATCH + 1))
  VERSION="${MAJOR}.${MINOR}.${PATCH}"
  echo "==> No version provided. Auto-incrementing patch: ${CURRENT} → ${VERSION}"
fi

if [[ "$FLAG" == "--test" ]]; then
  TWINE_REPO="https://test.pypi.org/legacy/"
  TARGET="TestPyPI"
else
  TWINE_REPO="https://upload.pypi.org/legacy/"
  TARGET="PyPI"
fi

# Load .env if present
if [[ -f ".env" ]]; then
  echo "==> Loading credentials from .env..."
  set -o allexport
  source .env
  set +o allexport
fi

echo "==> Bumping version to ${VERSION} in pyproject.toml..."
sed -i '' "s/^version = .*/version = \"${VERSION}\"/" pyproject.toml

echo "==> Cleaning previous builds..."
rm -rf dist/ build/ src/*.egg-info

echo "==> Building distribution packages..."
uv build

echo "==> Checking distribution with twine..."
uv run twine check dist/*

echo "==> Uploading to ${TARGET}..."
uv run twine upload --repository-url "${TWINE_REPO}" dist/*

echo "==> Done! Version ${VERSION} published to ${TARGET}."
