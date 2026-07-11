#!/usr/bin/env bash
# Switch the helao-async parent repo to a branch, then bring every nested
# private deployment repo under helao/deploy/* to the same branch (if it
# exists there) or to that repo's default branch otherwise.
set -u

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "usage: switch.sh <branch>              (parent + all nested repos)"
    echo "       switch.sh <deploy-folder> <branch>  (one nested repo only)"
    exit 1
fi

if [ "$#" -eq 2 ]; then
    ONLY_REPO="$1"
    TARGET="$2"
else
    ONLY_REPO=""
    TARGET="$1"
fi

# Activate the helao conda env if conda is available.
if command -v conda >/dev/null 2>&1; then
    # shellcheck disable=SC1091
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate helao
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Does branch $2 exist in repo $1 (local or on origin)?
branch_exists() {
    git -C "$1" show-ref --verify --quiet "refs/heads/$2" \
        || git -C "$1" show-ref --verify --quiet "refs/remotes/origin/$2"
}

# Print repo $1's default branch, resolved with a fallback chain.
default_branch() {
    local repo="$1" def
    def="$(git -C "$repo" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null)"
    def="${def#origin/}"
    if [ -z "$def" ]; then
        git -C "$repo" remote set-head origin -a >/dev/null 2>&1
        def="$(git -C "$repo" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null)"
        def="${def#origin/}"
    fi
    if [ -z "$def" ]; then
        local c
        for c in main master; do
            if git -C "$repo" show-ref --verify --quiet "refs/remotes/origin/$c"; then
                def="$c"
                break
            fi
        done
    fi
    if [ -z "$def" ]; then
        def="$(git -C "$repo" for-each-ref --format='%(refname:strip=3)' refs/remotes/origin/ 2>/dev/null | grep -vx HEAD | head -n1)"
    fi
    echo "$def"
}

# Switch repo $1 to $TARGET if present, else its default branch.
switch_repo() {
    local repo="$1" def
    git -C "$repo" fetch --all --quiet
    if branch_exists "$repo" "$TARGET"; then
        git -C "$repo" switch "$TARGET"
    else
        def="$(default_branch "$repo")"
        if [ -n "$def" ]; then
            echo "  '$TARGET' not found; switching to default '$def'"
            git -C "$repo" switch "$def"
        else
            echo "  cannot resolve default branch; leaving as-is"
        fi
    fi
}

if [ -n "$ONLY_REPO" ]; then
    repo="helao/deploy/$ONLY_REPO"
    if [ ! -d "$repo/.git" ]; then
        echo "no nested repo at $repo"
        exit 1
    fi
    echo "switching $repo branch"
    switch_repo "$repo"
    echo
    exit 0
fi

echo "switching helao-async branch"
git fetch --all && git switch main && git branch -D unstable && git switch unstable && git switch "$TARGET"

for repo in helao/deploy/*/; do
    [ -d "${repo}.git" ] || continue
    echo "switching ${repo%/} branch"
    switch_repo "${repo%/}"
done
echo
