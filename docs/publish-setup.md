# Publishing scubiee (PyPI + npm)

End users should install with **`uv tool install scubiee`** (recommended) or `pip install scubiee`. PyPI only updates when a release is uploaded — GitHub tags alone are not enough.

## One-time GitHub secrets

In **GitHub → repo → Settings → Secrets and variables → Actions**, add:

| Secret | Used for |
|--------|----------|
| `PYPI_API_TOKEN` | `uv tool install scubiee` / `pip install scubiee` ([create at pypi.org](https://pypi.org/manage/account/token/)) |
| `NPM_TOKEN` | `npm install -g scubiee` ([create at npmjs.com](https://www.npmjs.com/settings/~youruser/tokens)) |

## Release (automated)

1. Bump `version` in `pyproject.toml` and `npm/package.json` (keep them equal).
2. Commit and push.
3. Tag and push:

```bash
git tag v0.2.6
git push origin v0.2.6
```

Or re-run **Actions → publish → Run workflow** after fixing secrets.

## Release (manual, from maintainer machine)

```bash
python -m pip install -U build twine
python -m build
TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-XXXX python -m twine upload dist/scubiee-*
cd npm && npm login && npm publish --access public
```

## Verify

```bash
uv tool install scubiee   # recommended
scubiee setup --status

# or pip:
pip index versions scubiee
pip install -U scubiee
scubiee setup --status
```
