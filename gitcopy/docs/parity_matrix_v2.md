# V2 Parity Matrix

This matrix tracks v2 parity progress against Filmora behavior for in-scope features.

## Scope

- In scope: multi-track compositing, overlaps, speed curves/reverse, keyframed volume/ducking, common transitions, practical titles, practical color controls.
- Out of scope for v2.0: AI features and stabilization.

## Status Matrix

| Feature Area | Status | Notes |
| --- | --- | --- |
| Multi-track video compositing | In Progress | Interval-based compositor in v2 graph path. |
| Overlap compositing | In Progress | Deterministic z-order implemented. |
| Speed curves + reverse | In Progress | Piecewise integration used for timeline mapping. |
| Keyframed audio volume/ducking | In Progress | Envelope sampling applied per interval. |
| Transitions (common) | Planned | Parsed into IR; advanced render handling pending corpus tuning. |
| Titles/text (80/20) | In Progress | Drawtext overlay path for parsed title payloads. |
| Color controls (80/20) | In Progress | Basic eq/hue mapping for parsed color effects. |
| AI effects | Out of Scope (v2.0) | Explicitly deferred. |
| Stabilization | Out of Scope (v2.0) | Explicitly deferred. |

## Parity Gate

- Project-level pass: duration delta <= 100ms, SSIM >= 0.97, PSNR >= 40, audio mean-volume delta <= 2dB.
- Suite-level pass: at least 95% of corpus projects pass.

## Artifacts

- Required feature map: `parity/required_features_v2.json`
- Latest report: `parity/report.json`
- Private corpus manifest: local-only (`.gitignore`d)
