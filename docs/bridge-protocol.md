# Bridge protocol v1

[Documentation home](../README.md) · [Architecture](architecture.md)

Default base URL: `http://127.0.0.1:8765`. Every GET/POST requires `Authorization: Bearer YOUR_BRIDGE_TOKEN`. No endpoint returns Foundry credentials. The bridge exposes latest fresh positions, not a durable ordered movement log.

## Publish a move

`POST /moves` with `Content-Type: application/json`:

```json
{
  "scene_id": "YOUR_SCENE_ID",
  "columns": 12,
  "rows": 8,
  "piece_id": "goblin_1",
  "column": 3,
  "row": 2
}
```

Scene and dimensions must equal the bridge's startup configuration. Piece IDs are nonempty strings up to 128 characters. Column and row must be integers in the zero-based grid bounds. At most 64 distinct piece IDs can be stored per bridge process.

Success, HTTP 200:

```json
{"sequence": 7}
```

The sequence is assigned on acceptance. A successful response proves bridge acceptance, not a successful Foundry update. Publishing replaces that piece's previous retained event.

## Poll events

`GET /events?since=6` returns events newer than the cursor and accepted within the three-second freshness window:

```json
{
  "protocol": 1,
  "session": "example-session-id",
  "scene_id": "YOUR_SCENE_ID",
  "columns": 12,
  "rows": 8,
  "sequence": 7,
  "events": [
    {"piece_id": "goblin_1", "column": 3, "row": 2, "sequence": 7}
  ]
}
```

Events are sorted by sequence. The packet sequence is the service's latest accepted sequence even if events are empty or expired. Each response includes `Cache-Control: no-store`.

The session ID changes after restart. The Foundry client detects a changed session, resets its cursor, and refetches. On explicit Start it instead establishes a baseline and ignores movements already accepted. Successful mapped updates advance the cursor; failures leave it unchanged for retries while events remain fresh. Unpaired IDs are skipped.

There is no ACK endpoint, WebSocket channel, persistence, per-consumer delivery guarantee, or inactive-piece event.

## Errors and browser requests

| Status | Typical cause |
|---|---|
| 400 | Invalid cursor, JSON/object, scene, grid, piece ID, or coordinates |
| 403 | Missing/wrong token or disallowed Origin |
| 404 | Unknown endpoint |
| 413 | Missing/invalid body length or body larger than 16 KiB |

Browser `OPTIONS` requests from the configured origin receive HTTP 204 with allowed GET/POST methods, Authorization/Content-Type headers, and the private-network access header. Other origins are denied. Requests without Origin, such as the Python publisher, still require bearer authentication.

The module and publisher only accept an HTTP localhost/127.0.0.1 root URL, without credentials, query, or fragment. HTTPS bridge deployment would require implementation changes; setting an HTTPS URL alone is not supported.

## Logs and timing

Live-session JSONL is separate from the HTTP packet:

```json
{
  "piece_id": "goblin_1",
  "column": 3,
  "row": 2,
  "observed_at": 125.2,
  "emitted_at": 125.25,
  "observation_age_ms": 50.0
}
```

Values above are illustrative. `observed_at` is the observation's local monotonic timestamp; `emitted_at` is the session-loop timestamp used for emission. These are not wall-clock dates. HTTP events do not carry either timestamp. Bridge freshness starts at receipt, not camera capture.

The evaluator measures truth-settle to tracker-emission latency for correct first updates. It does not measure bridge delivery or Foundry acknowledgement latency.
