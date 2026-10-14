# Discord / Slack short post

Paste as is (about 700 characters). Link goes after the last line.

---

built trialgauntlet: a tiny agent reliability harness. reports pass^k (all k trials succeed) next to pass@k, and audits
every environment against no-op / random / always-refuse baselines before you trust it (all <= 0.7% on my three envs; a
naive state-diff grader lets a do-nothing agent hit 31-36%). scripted users + code graders, no LLM judge; injection and
fault wrappers; stdlib only, MIT. caveats: small synthetic envs, my own policies, and no real LLM has been run through
it yet (the README says so). feedback welcome, esp. on baselines I missed.
