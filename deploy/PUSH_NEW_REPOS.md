# Push split repos to GitHub

Two folders are generated locally (no secrets; `.env` never copied):

| Folder | GitHub repo purpose |
|--------|---------------------|
| `_publish/jyoti-backend-repo/` | FastAPI → **Railway** (root = repo root) |
| `_publish/jyoti-frontend-repo/` | **admin-app** + **customer-app** → two **Vercel** projects, roots `admin-app` / `customer-app` |

Regenerate after code changes:

```bash
./scripts/prepare-split-repos.sh
```

## 1. Create empty repos on GitHub

Under org **jyoti-creative-cards** (or your user), create **two** empty repos, e.g.:

- `jyoti-erp-api` (private recommended)
- `jyoti-erp-web` (private recommended)

Do **not** add README/license/gitignore in the GitHub wizard (keep repo empty).

## 2. Push backend

```bash
cd _publish/jyoti-backend-repo
git remote add origin https://github.com/jyoti-creative-cards/jyoti-erp-api.git
git push -u origin main
```

## 3. Push frontend

```bash
cd _publish/jyoti-frontend-repo
git remote add origin https://github.com/jyoti-creative-cards/jyoti-erp-web.git
git push -u origin main
```

Use SSH remotes if you prefer (`git@github.com:org/repo.git`).

## 4. Optional: GitHub CLI

If you install the **official** [GitHub CLI](https://cli.github.com/) (`gh`, not the npm package named `gh`), you can create and push in one step after `gh auth login`:

```bash
cd _publish/jyoti-backend-repo
gh repo create jyoti-creative-cards/jyoti-erp-api --private --source=. --remote=origin --push
```

## 5. Railway

New project → deploy from **`jyoti-erp-api`** → root directory **`.`** (repo root). Set env vars from your local `backend/.env` in the Railway UI.
