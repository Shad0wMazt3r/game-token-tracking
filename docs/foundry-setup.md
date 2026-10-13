# Foundry integration setup

Targets Foundry VTT v13, square-grid scenes, and one connected GM browser. The module runs inside the GM client, using its existing Foundry permissions to update TokenDocuments. Python never receives your Foundry password or session cookie. Live Foundry testing is still required; automated tests use simulated Foundry globals.

## 1. Install the module

Copy the repository directory `foundry/game-token-tracking` into your Foundry user-data directory at `Data/modules/game-token-tracking`. The module.json file must be directly inside that folder. Restart Foundry, open your world, and enable **Game Token Tracking** in Manage Modules.

Installation uses a local folder, not a downloadable manifest URL. A release archive/manifest installer is not provided yet.

## 2. Select the target scene

View a square-grid scene as GM. Create and run a Script macro:

```javascript
const tracker = game.modules.get("game-token-tracking").api;
const config = await tracker.useCurrentScene();
console.log("Tracker scene configuration", config);
ui.notifications.info("Target scene: " + config.sceneId);
```

The scene ID is shown in the notification and browser console. This initializes the board origin to the scene's playable top-left, accounting for canvas padding. If the physical board covers only part of the map, change Board origin X/Y in module settings to the pixel position of that region's first square. The board grid is uniform and uses the scene grid size.

## 3. Run the bridge

From the repository, with Python available:

```powershell
python -m token_tracker.bridge serve --scene-id YOUR_SCENE_ID --columns 12 --rows 8 --origin http://localhost:30000
```

Replace the scene ID and grid dimensions. The origin must exactly match the address used to open Foundry in your GM browser, including scheme, host and port, but without a path. For example, http://127.0.0.1:30000 is a different origin from http://localhost:30000.

The bridge prints a random token. In Foundry Settings > Configure Settings > Game Token Tracking, enter that token and keep the bridge URL as http://127.0.0.1:8765. The token is stored in the GM browser's client settings, not a shared world setting. Treat it as a local service secret; the settings field is not masked. The bridge binds only to loopback.

In a second PowerShell window, set the same token for manual moves and camera tracking:

```powershell
$env:TOKEN_TRACKER_KEY = "PASTE_THE_BRIDGE_TOKEN"
```

The bridge stays running in the first window. You can also set TOKEN_TRACKER_KEY there before launching it to reuse a key across restarts. Do not commit your token.

## 4. Pair pieces with tokens

Select exactly one placed token in the target scene. Run this Script macro once per piece:

```javascript
if (canvas.tokens.controlled.length !== 1) throw new Error("Select one token");
const pieceId = window.prompt("Physical piece ID / YOLO class name:");
if (pieceId) await game.modules.get("game-token-tracking").api.pair(pieceId);
```

The piece ID must match the detector's class name, such as goblin_1. Pairings are stored in world settings under the scene ID. One digital token can pair with only one physical piece; different physical pieces may share a grid square. Pairing changes stop tracking; restart it when ready.

To remove a pairing:

```javascript
await game.modules.get("game-token-tracking").api.unpair("goblin_1");
```

## 5. Start and test without a camera

Run this Script macro:

```javascript
await game.modules.get("game-token-tracking").api.start();
```

Then, in the second PowerShell window:

```powershell
python -m token_tracker.bridge move --scene-id YOUR_SCENE_ID --columns 12 --rows 8 --piece-id goblin_1 --column 3 --row 2
```

Coordinates start at zero. This should place the paired token in the fourth column and third row of your configured physical-board region. Send test moves only after starting the module: start intentionally ignores earlier moves.

For tokens larger than one square, the reported cell is the top-left square of the footprint. This MVP does not center a large token around a mini's physical base.

Stop macro:

```javascript
game.modules.get("game-token-tracking").api.stop();
```

Debug macro:

```javascript
console.log(game.modules.get("game-token-tracking").api.status());
console.table(game.modules.get("game-token-tracking").api.tokens());
```

## 6. Connect the camera tracker

After installing the vision dependencies, calibrating the board, and training custom pose weights:

```powershell
python -m token_tracker.cli track --source 0 --calibration calibration.json --weights best.pt --bridge http://127.0.0.1:8765 --scene-id YOUR_SCENE_ID
```

Calibration dimensions must match the bridge dimensions. Confirmed moves go both to stdout as JSON and to the bridge. A background sender retries the latest pending move for up to three seconds so an unavailable bridge does not block camera inference.

## Behavior and limitations

- Only the configured scene and manually paired tokens can move. Viewing another scene stops tracking.
- Unknown pieces are ignored. Missing pieces do not delete or move tokens.
- Failed document updates are retried while the event remains fresh. Successful updates are idempotent.
- The bridge retains only the latest position per piece and expires it after three seconds. Long outages can drop a move; move the physical piece again or issue a fresh manual move.
- Polling adds approximately 100 ms plus network/document-update time. The project's 500 ms target is not yet measured.
- Use only one GM browser for tracking. Multi-GM leadership/leases are not implemented.
- Scenes must be square-grid and the physical board region must fit inside the playable scene. Walls, movement budgets, combat rules and game-system constraints are not enforced by this positional sync.
- Integration does not write movement back into the physical tracker.
- A browser may request permission to access localhost/private networks. Hosting Foundry behind HTTPS or a strict CSP can block the request. Verify the local HTTP setup first; hosted deployment may require an HTTPS bridge or a same-origin reverse proxy. Do not disable browser security protections.

## Automated checks

```powershell
python -m unittest discover -s tests -v
node --test tests/foundry/core.test.mjs tests/foundry/module.test.mjs
```

These cover the real localhost HTTP protocol and simulated Foundry lifecycle, geometry, retries, restart handling and GM/scene checks. They do not replace testing in your actual Foundry version and game system.

## API references

- https://foundryvtt.com/article/module-development/
- https://foundryvtt.com/api/v13/classes/foundry.documents.TokenDocument.html
- https://foundryvtt.com/api/v13/classes/foundry.documents.Scene.html
