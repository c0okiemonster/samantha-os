# Branch Protection Setup

Run these commands **once** after pushing the repo to GitHub. Requires [`gh` CLI](https://cli.github.com/) authenticated.

## Protect `main` branch

```bash
gh api -X PUT repos/c0okiemonster/samantha-os/branches/main/protection \
  --input - <<EOF
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Lint Python",
      "Docker Compose Build",
      "Security Scan"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "require_last_push_approval": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": true
}
EOF
```

## What this enforces

- ✅ PRs require at least 1 approval
- ✅ CODEOWNERS review required (you — @c0okiemonster)
- ✅ All CI checks must pass (lint, build, security)
- ✅ Stale reviews dismissed on new commits
- ✅ Conversations must be resolved before merge
- ❌ Force pushes to `main` blocked
- ❌ Branch deletion blocked
- ❌ Direct pushes from anyone else blocked

## Fork settings

To configure fork policies (Settings → General → Features):

- **Allow forking**: ON (public contributions)
- **Discussions**: ON (community conversations)
- **Issues**: ON (bug reports)
- **Projects**: Optional

## Disable risky features

```bash
gh api -X PATCH repos/c0okiemonster/samantha-os \
  -f allow_merge_commit=false \
  -f allow_rebase_merge=false \
  -f allow_squash_merge=true \
  -f delete_branch_on_merge=true \
  -f allow_auto_merge=false
```

This enforces:
- ✅ Squash merges only (clean history)
- ✅ Branches auto-deleted after merge
- ❌ Merge commits blocked
- ❌ Rebase merges blocked
- ❌ Auto-merge blocked (requires explicit approval)

## Signed commits (optional but recommended)

```bash
gh api -X POST repos/c0okiemonster/samantha-os/branches/main/protection/required_signatures
```

Requires all commits to `main` to be GPG-signed.

## Verify

```bash
gh api repos/c0okiemonster/samantha-os/branches/main/protection | jq
```
