# How to Commit This Bundle to GitHub

This file is a one-time reference for getting the initial commit pushed to the `SolaceLabs/sap-pm-demo` repository. After this is done once, you can delete this file (it's intentionally not committed).

---

## Prerequisites

- The empty `SolaceLabs/sap-pm-demo` repo exists on GitHub (you created it)
- You have Git installed on your Mac
- You're authenticated to GitHub (either SSH key or `gh` CLI or HTTPS with credential helper)

## Steps

### 1. Clone the empty repo

On your Mac:

```bash
cd ~/Documents   # or wherever you keep code
git clone https://github.com/SolaceLabs/sap-pm-demo.git
cd sap-pm-demo
```

You should see an empty directory (just a `.git` folder).

### 2. Extract this bundle into the cloned repo

If you got this bundle as a zip, unzip it. Then copy all the files into the cloned repo:

```bash
# Assuming the bundle is at ~/Downloads/sap-pm-demo-bundle/
# and the cloned repo is at ~/Documents/sap-pm-demo/

# Copy everything (including hidden files like .gitignore)
cp -R ~/Downloads/sap-pm-demo-bundle/. ~/Documents/sap-pm-demo/

cd ~/Documents/sap-pm-demo
ls -la   # should show all the files
```

### 3. Verify nothing sensitive is included

```bash
# Make sure there's no .env file
ls -la agent/.env 2>/dev/null && echo "❌ STOP! .env exists — remove it" || echo "✅ No .env"

# Make sure no .key files
find . -name "*.key" -not -path "./.git/*" | head
# Should output nothing

# Make sure no __pycache__
find . -name "__pycache__" -not -path "./.git/*"
# Should output nothing or only filtered ones

# Check .gitignore is in place
cat .gitignore | head -20
# Should show the comprehensive .gitignore content
```

If any of those checks find something — **stop and clean up before committing**. Once committed to a public repo, it's effectively permanent.

### 4. Make the scripts executable

```bash
chmod +x agent/run_agent.sh
chmod +x agent/run_simulator.sh
```

### 5. Add, commit, and push

```bash
# Add everything
git add .

# Verify what's being added (sanity check)
git status

# Look at the file list — make sure no .env, *.key, or other secrets are in it
# If anything looks wrong, run: git reset HEAD <bad-file>

# Commit
git commit -m "Initial commit: SAP PM Demo with maintenance agent, dashboard, specs, and docs"

# Push to main
git push -u origin main
```

You should see successful push output. Go to https://github.com/SolaceLabs/sap-pm-demo to verify everything appears.

### 6. Verify the public repo looks right

In your browser, visit https://github.com/SolaceLabs/sap-pm-demo and confirm:

- README.md displays correctly on the repo home page
- All directories are visible (agent/, web/, specs/, deploy/, docs)
- LICENSE shows as "Apache 2.0" in GitHub's UI
- No `.env`, `*.key`, or other sensitive files visible

### 7. Delete this file

Once committed, this file has served its purpose. You can delete it locally and re-push, or just ignore it:

```bash
rm COMMIT_INSTRUCTIONS.md
git add -A
git commit -m "Remove one-time commit instructions"
git push
```

---

## Going Forward

After this initial commit, the workflow is:

```bash
# Edit files
# Then:
git add .
git commit -m "Description of what changed"
git push
```

For new file deliveries from Claude, the pattern is:

1. Claude provides updated files
2. You drop them into the local clone (replacing existing or adding new)
3. Review the diff: `git diff`
4. Commit and push

When deploying changes to EC2:

```bash
ssh ubuntu@ec2-54-219-47-90.us-west-1.compute.amazonaws.com
cd /home/ubuntu/sap/ai/pm-demo
git pull
# Restart any affected services
```
