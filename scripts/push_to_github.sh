#!/usr/bin/env bash
# Script to verify authentication and push to GitHub repository
set -e

REPO_NAME="${1:-AOUL}"
USER_NAME="iblametal"
USER_EMAIL="Miyuki09080@gmail.com"

cd "$(dirname "$0")/.."

echo "==> Configuring Git Author details..."
git config user.name "$USER_NAME"
git config user.email "$USER_EMAIL"

echo "==> Current Remote:"
git remote -v

echo "==> Testing SSH Authentication with GitHub..."
if ssh -T -o ConnectTimeout=5 git@github.com 2>&1 | grep -q "successfully authenticated"; then
    echo "✅ SSH Authentication successful!"
    echo "==> Pushing to git@github.com:$USER_NAME/$REPO_NAME.git..."
    git remote set-url origin "git@github.com:$USER_NAME/$REPO_NAME.git"
    git branch -M main
    git push -u origin main
    echo "🎉 Successfully pushed repository to https://github.com/$USER_NAME/$REPO_NAME"
else
    echo "⚠️ SSH key not yet added to GitHub account '$USER_NAME'."
    echo "   Public Key:"
    cat ~/.ssh/id_ed25519.pub
    echo ""
    echo "   Please add the above key at: https://github.com/settings/keys"
    echo "   Then re-run: ./scripts/push_to_github.sh"
    exit 1
fi
