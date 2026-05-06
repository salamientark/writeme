<!-- Generated: 2026-05-06 | Files scanned: 3 | Token estimate: ~300 -->

# Data

No database. Persistence = filesystem only.

## On-disk artifacts
| Path | Owner | Purpose |
|------|-------|---------|
| `$XDG_CACHE_HOME/writeme/repos/<owner>/<name>/` | `state.xdg_cache_dir` + `_clone_or_fetch` | Shallow git clones, reused across runs |
| `$XDG_STATE_HOME/writeme/state.json`            | `StateStore` | Processed-repo set + per-repo result |
| `$XDG_STATE_HOME/writeme/.lock`                 | `safety.acquire_lock` | fcntl flock, single-instance |
| `mktemp -d` sandbox                             | `install.sh` | Self-deleting launcher dir |

## state.json shape
```jsonc
{
  "version": 1,
  "user": "salamientark",
  "started_at": "2026-05-06T07:00:00Z",
  "processed": {
    "<owner>/<repo>": {
      "result": "accepted|discard|skipped|error",
      "mode": "pr|direct|commit-only",
      "pr_url": "https://github.com/...",   // optional
      "ts": "2026-05-06T07:01:23Z"
    }
  }
}
```

## External data sources
| Source | Access | Where |
|--------|--------|-------|
| GitHub repos | `gh api graphql` | `fetch._fetch_page` |
| GitHub rate limit | same response | `fetch._handle_rate_limit` |
| Repo file content | `git`, `Path.read_text` | `review._read_file`, `_blast_radius_ok` |
| Claude output | subprocess stdout | `review._invoke_claude` |

## Migrations
None. State file is forward-evolved by `StateStore.load` (defensive defaults).
