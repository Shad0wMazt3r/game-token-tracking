# Validation plan

[Documentation home](../README.md) · [Walkthrough](prototype-walkthrough.md)

Passing automated checks establishes software behavior under tested inputs. It does not establish recognition quality, webcam usability, live Foundry compatibility, or the full latency target.

## Evidence ladder

| Stage | Procedure | Evidence to retain |
|---|---|---|
| Software checks | Run Python and Node suites; inspect CI | Commit SHA, environment, outputs |
| Foundry without vision | Pair one token; Start; issue manual moves | Foundry version/system, browser, screen recording |
| Geometry without training | Calibrate each actual camera; inspect unused grid references | Placements, dimensions, residuals, reference errors |
| Data tooling | Capture independent sessions; annotate representative frames; split | Class inventory, manifests, split report, label review |
| Trained single view | Run held-out moves and inspect base keypoints | Weights, config, truth and prediction logs |
| Two-view pipeline | Repeat with overlap, hands, missing frames, and disagreement | Results stratified by scenario |
| End-to-end synchronization | Time physical settling to actual Foundry update | Measurement method, per-move timings, p50/p95 |

## Manual Foundry acceptance checklist

- [ ] Fresh move after Start reaches the paired token at the expected zero-based cell.
- [ ] Unpaired IDs leave all tokens unchanged.
- [ ] Pairings survive a browser reload.
- [ ] Switching scenes stops synchronization.
- [ ] Pairing and configuration changes require an explicit restart.
- [ ] Stop prevents subsequent fresh moves from being applied.
- [ ] Explicit Start ignores movements already accepted by the bridge.
- [ ] Bridge restart is handled; key changes are reconfigured when needed.
- [ ] Deleted paired tokens produce a visible error.
- [ ] Incorrect origins/keys are rejected.
- [ ] Board region and large token footprint checks match the intended map.
- [ ] The chosen browser permits the deployment's local-service requests.

Record failures rather than checking boxes based on simulated tests. Use a disposable test scene.

## Geometry acceptance

Keep both cameras in their final unmounted placements. Check unused intersections near the front, back, sides, and overlaps. Compare projected coordinates with known coordinates in cell units. Do not infer quality from the four fitted corner points alone.

Record areas where bases cannot be seen, projection sensitivity is high, or one view contradicts the other. These observations determine whether camera coverage supports the intended board before spending time on training.

## Recognition trials

Use a held-out recording session with at least 100 deliberate moves as an initial evaluation. Record ordinary placements, rotations, hand occlusion, overlap, same-square pieces, near-boundary placements, and confusing identities separately. Include removals, which should preserve the confirmed position under current behavior.

Ground-truth JSONL:

```json
{"piece_id":"goblin_1","column":3,"row":2,"settled_at":125.0}
```

`settled_at` must share the tracker's monotonic clock. The evaluator does not collect ground truth or align independent clocks. Arrange shared-clock collection or a documented alignment before scoring.

```powershell
python -m token_tracker.evaluate truth.jsonl moves.jsonl --window 3 --output evaluation.json
```

Report correct, wrong, missed, and extra updates; retain both inputs. A wrong first update remains wrong even if a later update corrects it. The default matching window is three seconds and ends earlier if another truth move for the same piece begins.

The live log is append-only. Use a fresh log per trial; mixing unrelated runs or clock domains invalidates timing.

## Targets and measurement limits

The project's 95% correct-grid target and p50 below 500 ms are acceptance goals, not current results. Define the trial mix and denominator before collecting evidence. Report sample counts and the performance of difficult scenarios separately.

Current scoring ends at tracker emission. True end-to-end timing must include capture, inference, stability, publishing, browser polling, and Foundry document application. Those stages are not all instrumented. A screen recording can provide coarse visible-update timing if physical and digital events are captured together; it does not by itself give precise document acknowledgement timestamps.

## Handoff record

Retain the commit SHA, dependency versions, OS/browser, Foundry version and system, webcam models and placements, actual resolutions, board dimensions, calibration files, class inventory, model run/weights, configuration, test scenario counts, truth/prediction logs, and unresolved failures. Keep bridge keys out of the record.

## Remaining work before a validated system

| Gap | Needed next |
|---|---|
| No trained weights | Actual footage, consistent labels, held-out evaluation |
| No live Foundry evidence | Licensed v13 world and team acceptance run |
| No full latency instrumentation | Capture-to-update timestamps and a shared timing method |
| No synthetic observation replay harness | Deterministic camera-independent pipeline input |
| No explicit inactive state | Product decision and removal/recovery implementation |
| No automatic camera reopen | Disconnect detection and bounded reconnect behavior |
| Identical-piece ambiguity | Manual recovery or a changed identity strategy |

These are implementation or evidence gaps, not assumptions that can be resolved by documentation.
