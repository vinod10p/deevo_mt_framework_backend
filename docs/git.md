Untrack without deleting them from disk:



git rm -r --cached '**/__pycache__' '*.pyc'
git commit -m "Stop tracking Python bytecode"


-- create a new branch 

it create new branch


Git checkout main
Git pull origin main

Git checkout -b v4.0

Git push -u origin v4.0


Step	Command	Description
1	git checkout main	Switch to main branch
2	git pull origin main	Sync latest main code
3	git checkout -b v4.0	Create new local branch
4	git push -u origin v4.0	Push new branch to GitHub

4. When you finally figure it out
Once the API integration is finished, working perfectly, and you are happy with it, you can merge it back into your stable main branch:


# Switch back to the stable branch
git checkout main 

# Bring in all the good API code you just wrote
git merge feature/api-integration

---
twilio api:core:messages:create \
  --from "+14324232204" \
  --to "+19174129434" \
  --body "Test message from Deevolight"

---

ulid generation 
uv run python -c "from mtf.shared.security import generate_id; print(generate_id())"