# Contributing

## Setup

```powershell
python -m pip install -e .[dev]
```

## Before Opening a PR

1. Run tests:
   ```powershell
   python -m pytest -q
   ```
2. Keep changes focused and include/update tests when behavior changes.
3. Keep Windows GUI behavior and CLI behavior aligned where possible.

## Coding Notes

- Python target: 3.10+
- Prefer explicit, readable logic over clever compact code.
- Do not commit generated build artifacts (`build/`, `dist/`, `dist_*`).

## Pull Requests

- Describe the problem and the exact behavior change.
- Include screenshots for GUI changes.
- Mention any known limitations or follow-up work.
