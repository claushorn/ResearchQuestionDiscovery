# Frontend

A local web app over the pipeline's stores: see what every stage produced, triage it, and run the next stage on a
selection as an **Agent Task** (the stage's own CLI in the background).

```bash
uv run frontend            # http://127.0.0.1:8765/ (opens the browser)
```

Configuration: `config.yaml` (port, rows per page, stage directories). It binds to 127.0.0.1 only.
