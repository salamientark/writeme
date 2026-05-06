# Release Checklist

Per-version steps for cutting a `gh-readme-pipeline` release.

Two paths:

- **Automated (recommended):** push tag → `release.yml` workflow pins SHA, creates release branch, publishes GitHub Release.
- **Manual:** run the steps locally. Use only if CI is broken.

---

## Automated release (tag push)

### 1. Pre-flight

- [ ] `python -m unittest discover -s tests` — all green.
- [ ] `git status` clean on `main`, branch up to date with `origin/main`.
- [ ] README install URL references the upcoming tag.
- [ ] `CHANGELOG.md` (if maintained) updated.
- [ ] Optional: write `docs/releases/vX.Y.Z.md`. If absent, GitHub auto-generates notes.

### 2. Tag and push

```bash
VERSION=v0.1.0
git tag -a "$VERSION" -m "Release $VERSION"
git push origin "$VERSION"
```

Tag must match `^v\d+\.\d+\.\d+([.-][A-Za-z0-9.]+)?$` or workflow rejects it.

### 3. What `release.yml` does

Triggered by `push` of any `v*` tag. Steps:

1. Checkout + Python 3.11 + run unittest suite.
2. Resolve tag → commit SHA via `git rev-parse "${VERSION}^{commit}"`.
3. Pin `EXPECTED_SHA` in `install.sh` to that commit SHA.
4. Create `release/${VERSION}` branch with the pinned commit, push to origin.
5. `gh release create` — uses `docs/releases/${VERSION}.md` if present, else `--generate-notes`. Attaches `install.sh` and `gh_readme_pipeline.py`.
6. Fast-forward `latest` branch to the pinned commit.

### 4. Watch the run

```bash
gh run list --workflow=release.yml --limit 5
gh run watch
```

### 5. Verify

- [ ] `curl -fsSL https://raw.githubusercontent.com/salamientark/writeme/$VERSION/install.sh | bash` on a clean VM.
- [ ] Tampered SHA test: edit local `install.sh`, set wrong `EXPECTED_SHA`, run → exit `3`.
- [ ] Confirm sandbox wiped on success, preserved on failure.

> **CDN cache:** `raw.githubusercontent.com` caches branch refs (~5 min). If you
> re-push `release/$VERSION`, the tag URL serves stale content briefly. Either
> wait, bust with `?$(date +%s)`, or fetch by commit SHA path (never cached).

### 6. Post-release

- [ ] Bump `EXPECTED_SHA` back to all-zeros on `main` for unpinned dev mode.
- [ ] Announce in repo README "Latest release" badge / link.

---

## Workflow triggers

### `release.yml`

| Trigger | How | Effect |
|---------|-----|--------|
| Tag push | `git push origin vX.Y.Z` | Full release: pin, branch, GitHub Release, `latest` ff |
| Manual dry-run | `gh workflow run release.yml -f tag=vX.Y.Z -f dry_run=true` | Resolve SHA, pin in workspace, log what *would* happen. No branch push, no release |
| Manual real-run | `gh workflow run release.yml -f tag=vX.Y.Z -f dry_run=false` | Same as tag push, for an existing tag |

Dry-run requires the tag to already exist on the repo.

### `test.yml`

Runs on:
- `push` to `main`
- any `pull_request`
- manual: `gh workflow run test.yml`

Matrix: Python 3.10 / 3.11 / 3.12 + `shellcheck install.sh`.

### Useful gh commands

```bash
gh workflow list
gh workflow view release.yml
gh run list --workflow=release.yml
gh run view <run-id> --log
gh run rerun <run-id>
gh run cancel <run-id>
```

---

## Manual fallback (CI down)

Use only if `release.yml` is broken. Mirrors what the workflow does.

### 1. Tag

```bash
VERSION=v0.1.0
git tag -a "$VERSION" -m "Release $VERSION"
SHA=$(git rev-parse "$VERSION^{commit}")
echo "$SHA"
```

> **Important:** use `$VERSION^{commit}`, not `$VERSION`. Annotated tags
> (`tag -a`) are objects with their own SHA; bare `rev-parse` returns the tag
> object SHA, not the commit it points to. The launcher fetches the *commit* —
> pinning the tag SHA causes exit `3` (mismatch) for every user.

### 2. Pin SHA in install.sh

```bash
# edit install.sh: EXPECTED_SHA="${EXPECTED_SHA:-<paste $SHA here>}"
git checkout -b release/$VERSION
git commit -am "chore: pin EXPECTED_SHA for $VERSION"
```

Do not retag. The launcher served from the release branch carries the pinned SHA; `main` stays unpinned for dev.

### 3. Push & create release

```bash
git push origin "$VERSION"
git push origin release/$VERSION

NOTES_ARG="--generate-notes"
if [ -f "docs/releases/$VERSION.md" ]; then
  NOTES_ARG="--notes-file docs/releases/$VERSION.md"
fi

gh release create "$VERSION" \
  --title "$VERSION" \
  $NOTES_ARG \
  install.sh \
  gh_readme_pipeline.py

git push origin "+release/$VERSION:refs/heads/latest"
```

### 4. Verify + post-release

Same checks as automated path (sections 5 and 6 above).
