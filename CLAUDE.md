# CLAUDE.md

@AGENTS.md

When you change a template file, render base + this overlay and read the *output*:

```sh
uv run pytest tests/test_go.py -k "checks_pass or definition_of_done"
```
