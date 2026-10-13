# Troubleshooting

[Documentation home](../README.md) · [Foundry setup](foundry-setup.md)

Debug in this order: manual Foundry move → camera availability → calibration → single-view detection → fusion → full synchronization. Keep the manual bridge test available so model failures can be separated from Foundry failures.

| Symptom | Check and action |
|---|---|
| Module does not appear | Confirm `Data/modules/game-token-tracking/module.json` exists directly in the module folder; restart Foundry and enable it in the world |
| No Token Tracker button | Log in as GM; check the browser console and module enablement |
| Bridge HTTP 403 | Re-enter the current key; confirm exact browser origin, including localhost vs 127.0.0.1 and port |
| Fetch fails without HTTP response | Verify service is running on the GM browser's machine; inspect console for CORS, CSP, mixed-content, or private-network permission failures |
| Token does not move | Check target scene, exact class/piece ID, pairing to a placed token, and Start; send a fresh manual move after Start |
| Token moves to wrong map region | Reinitialize current scene, check origin and padding, and confirm zero-based grid coordinates |
| Large token appears offset | Current convention maps the piece cell to the token footprint's top-left; it does not center a multi-square token |
| Tracking stops unexpectedly | Scene changes, pairing edits, or connection settings stop tracking intentionally; restart after configuration |
| Restarted bridge rejects requests | A generated key changed; reuse an environment key or copy the new key into all clients |
| Camera cannot open | Try the correct index, close other camera apps, check OS camera permission and USB connection |
| Camera stops supplying frames | Session does not automatically reopen the device; stop, reconnect, and restart |
| Resolution differs from calibration | Match requested dimensions and recalibrate at the actual negotiated size |
| Calibration rejected | Use correctly ordered, spread-out, non-collinear references; verify board coordinates and avoid almost edge-on coverage |
| Correct detector but wrong cell | Inspect the base keypoint and homography at unused references; check sensitivity, lens distortion, and projection outside reference coverage |
| Human-pose weights rejected | Train the custom `kpt_shape: [1,3]` miniature dataset; stock human-pose weights are incompatible |
| Piece disappears from overlay | Check confidence, duplicate-class detections, occlusion, age, bounds, and geometric sensitivity |
| Each view works but fusion holds | Look for conflicting positions of the same class; check both calibrations against shared board intersections |
| No movement despite visibility | Stability resets on jitter/gaps; cell may already be confirmed; test R resync and review throughput |
| Same cell remains after removal | Last confirmed position is deliberately held; automatic inactive/removal state is not implemented |
| Move lost after outage | Events expire and only latest positions are retained; send a fresh manual move or use R after the connection returns |
| Dataset split fails | Check three independent labeled sessions, consistent class order, training coverage, valid labels, and duplicate image bytes |
| Training fails on GPU | Confirm the installed PyTorch build supports the GPU; CPU is available for a slower initial run |

## Useful inspection

From a Foundry Script macro or browser console:

```javascript
const tracker = game.modules.get("game-token-tracking").api;
console.log(tracker.status());
console.table(tracker.tokens());
console.log(tracker.pairings());
```

Status includes running state, target scene, cursor, bridge session, last error, and last reported board dimensions. It does not include per-camera diagnostics or Foundry update timing.

For live tracking, capture stderr along with the optional move log. Record camera placement, negotiated dimensions, model path, config, and reproduction steps. Redact bridge keys before sharing output.

## Browser topology

An HTTP Foundry instance on the same computer is the simplest initial test. Hosted HTTPS Foundry may block local HTTP requests depending on the browser and server policy. The current URL validators only support HTTP loopback, so an HTTPS bridge or same-origin proxy is future engineering work. Do not disable browser security protections to conceal an integration failure.

## Resynchronization

After fixing the bridge or pairing, Start the Foundry module before emitting fresh positions. In the live camera session press R to clear confirmed cells; newly stable observations can then be sent again. R does not infer hidden-piece locations or recover identical-piece identity.
