# Discord / Slack short post

Paste as is (under 800 characters, link included). Every number comes from `results/*.json` and matches the README tables.

---

built trialgauntlet: a tiny agent reliability harness (stdlib python, MIT). reports pass^k (all k trials succeed) next to pass@k, and audits each env against do-nothing agents first (baselines <= 0.7%; a naive grader lets do-nothing pass 31-36%). first real runs: Qwen3 4B/8B/14B, n=4 trials/task, k=2, one machine. 8B stock on fleet: pass@1 55.3%, pass^2 40.1%. 8B stock vs ablated pass@1: indistinguishable on fleet and ledger, config 15.3% vs 5.7%. 4B stock: 0.0%, a chat-template format artefact. caveats: small synthetic envs, my own graders, n=4 is noisy, so leads not results. https://github.com/Intermountainh8ter/trialgauntlet
