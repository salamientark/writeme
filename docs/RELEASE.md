# Release Checklist

Per-version steps for cutting a `gh-readme-pipeline` release.

## 1. Pre-flight

- [ ] `python -m unittest discover -s tests` — all green.
- [ ] `git status` clean on `main`.
- [ ] README install URL references the upcoming tag.
- [ ] `CHANGELOG.md` (if maintained) updated.

## 2. Tag

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

## 3. Pin SHA in install.sh

Edit `install.sh`:

```bash
EXPECTED_SHA="${EXPECTED_SHA:-<paste $SHA here>}"
```

Commit on a release branch (do not retag):

```bash
git checkout -b release/$VERSION
git commit -am "chore: pin EXPECTED_SHA for $VERSION"
```

The launcher hosted on GitHub raw should come from the release branch, so users
get the pinned SHA by default while `main` stays unpinned for development.

## 4. Push & GitHub Release

```bash
git push origin "$VERSION"
git push origin release/$VERSION

gh release create "$VERSION" \
  --title "$VERSION" \
  --notes-file docs/RELEASE-NOTES-$VERSION.md \
  install.sh \
  gh_readme_pipeline.py
```

## 5. Verify

- [ ] `curl -fsSL https://raw.githubusercontent.com/salamientark/writeme/$VERSION/install.sh | bash` on a clean VM.
- [ ] Tampered SHA test: edit local `install.sh`, set wrong `EXPECTED_SHA`, run → exit `3`.
- [ ] Confirm sandbox wiped on success, preserved on failure.

> **CDN cache:** `raw.githubusercontent.com` caches branch refs (~5 min). If you
> re-push `release/$VERSION`, the tag URL serves stale content briefly. Either
> wait, bust with `?$(date +%s)`, or fetch by commit SHA path (never cached).

## 6. Post-release

- [ ] Bump `EXPECTED_SHA` back to all-zeros on `main` for unpinned dev mode.
- [ ] Announce in repo README "Latest release" badge / link.
