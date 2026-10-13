import {installPanel} from "./panel.mjs";
import {validatePacket, tokenPosition, loopbackURL} from "./core.mjs";
const ID = "game-token-tracking";
let timer = null, controller = null, running = false, cursor = 0, session = null, generation = 0;
let lastError = "", lastPacket = null;
const setting = key => game.settings.get(ID,key);
const requireGM = () => { if (!game.user.isGM) throw new Error("GM required"); };

Hooks.once("init", () => {
  const fields = {
    bridgeURL: {name:"Tracker bridge URL",type:String,default:"http://127.0.0.1:8765"},
    bridgeKey: {name:"Tracker bridge token",hint:"Stored in this browser only. Do not share it.",type:String,default:""},
    sceneId: {name:"Target scene ID",hint:"Tracking stops when another scene is viewed.",type:String,default:""},
    originX: {name:"Board origin X (Foundry pixels)",hint:"Top-left of the first board square, including scene padding.",type:Number,default:0},
    originY: {name:"Board origin Y (Foundry pixels)",type:Number,default:0}
  };
  for (const [key,data] of Object.entries(fields)) {
    game.settings.register(ID,key,{...data,scope:"client",config:true,onChange:()=>stop()});
  }
  game.settings.register(ID,"pairings",{scope:"world",config:false,type:Object,default:{}});
});

function stop() {
  generation++; running = false;
  clearTimeout(timer); timer = null;
  controller?.abort(); controller = null;
}

function geometry(scene) {
  if (scene.grid.type !== CONST.GRID_TYPES.SQUARE) throw new Error("Square grid required");
  const d = scene.dimensions;
  return {size:scene.grid.size,originX:setting("originX"),originY:setting("originY"),
    sceneX:d.sceneX,sceneY:d.sceneY,sceneWidth:d.sceneWidth,sceneHeight:d.sceneHeight};
}

async function request(since, signal) {
  const response = await fetch(loopbackURL(setting("bridgeURL"))+"/events?since="+since,{
    headers:{Authorization:"Bearer "+setting("bridgeKey")},cache:"no-store",signal
  });
  if (!response.ok) throw new Error("Bridge HTTP "+response.status);
  return validatePacket(await response.json(),setting("sceneId"));
}

async function tick(epoch) {
  if (!running || epoch !== generation) return;
  let timeout, requestController;
  try {
    requireGM();
    const scene = canvas.scene;
    if (!canvas.ready || scene?.id !== setting("sceneId")) {
      stop(); throw new Error("Target scene is not viewed. Tracking stopped.");
    }
    const g = geometry(scene);
    requestController = new AbortController(); controller=requestController;
    timeout = setTimeout(()=>requestController.abort(),2000);
    let packet = await request(cursor,requestController.signal);
    if (!running || epoch !== generation) return;
    // A restarted bridge has a new session and starts its sequence at zero.
    if (session !== packet.session) {
      session=packet.session; cursor=0;
      packet=await request(0,requestController.signal);
      if (!running || epoch !== generation) return;
    }
    lastPacket = packet;
    const mappings = setting("pairings")[scene.id] ?? {};
    for (const event of packet.events) {
      if (!running || epoch !== generation || canvas.scene?.id !== scene.id) return;
      if (event.sequence <= cursor) continue;
      const tokenId = Object.hasOwn(mappings,event.piece_id) ? mappings[event.piece_id] : null;
      if (!tokenId) continue;
      const token = scene.tokens.get(tokenId);
      if (!token) throw new Error("Paired token no longer exists: "+event.piece_id);
      const position = tokenPosition(event,packet,g,token);
      if (token.x !== position.x || token.y !== position.y) {
        await token.update(position,{animate:false});
      }
    }
    // Advance only after every mapped update succeeds; retries are idempotent.
    cursor=packet.sequence; lastError="";
  } catch(error) {
    if (running || error.message.includes("Tracking stopped")) {
      if (lastError !== error.message) ui.notifications.warn("Token tracker: "+error.message);
      lastError=error.message;
    }
  } finally {
    clearTimeout(timeout);
    if (controller === requestController) controller=null;
    if (running && epoch === generation) timer=setTimeout(()=>tick(epoch),100);
  }
}

async function start() {
  requireGM(); stop();
  if (!setting("bridgeKey")) throw new Error("Set the bridge token in module settings");
  if (!canvas.ready || canvas.scene?.id !== setting("sceneId")) throw new Error("View the configured target scene");
  geometry(canvas.scene);
  // Baseline suppresses stale movements published before the GM explicitly starts.
  const epoch = generation;
  const baseline = await request(0,AbortSignal.timeout(2000));
  if (epoch !== generation) return;
  session=baseline.session; cursor=baseline.sequence; lastPacket=baseline;
  running=true; lastError=""; tick(epoch);
  ui.notifications.info("Token tracking started");
}

async function pair(pieceId, tokenId=canvas.tokens.controlled[0]?.document.id) {
  requireGM(); stop();
  const scene=canvas.scene;
  if (!scene || scene.id !== setting("sceneId")) throw new Error("View the configured target scene");
  if (typeof pieceId !== "string" || !pieceId.trim() || pieceId.length > 128 || !scene.tokens.get(tokenId)) throw new Error("Piece ID and scene token required");
  const all=structuredClone(setting("pairings"));
  const mappings=all[scene.id] ?? {};
  if (Object.entries(mappings).some(([piece,id])=>piece !== pieceId && id === tokenId)) throw new Error("Token is already paired with another piece");
  Object.defineProperty(mappings,pieceId,{value:tokenId,enumerable:true,writable:true,configurable:true});
  all[scene.id]=mappings;
  await game.settings.set(ID,"pairings",all);
  ui.notifications.info("Paired "+pieceId+". Restart tracking when ready.");
}

async function unpair(pieceId) {
  requireGM(); stop();
  const all=structuredClone(setting("pairings"));
  if (all[canvas.scene?.id]) delete all[canvas.scene.id][pieceId];
  await game.settings.set(ID,"pairings",all);
}

async function useCurrentScene() {
  requireGM(); stop();
  if (!canvas.ready || !canvas.scene) throw new Error("View a scene first");
  const scene=canvas.scene;
  if (scene.grid.type !== CONST.GRID_TYPES.SQUARE) throw new Error("Square grid required");
  const d=scene.dimensions;
  await game.settings.set(ID,"sceneId",scene.id);
  await game.settings.set(ID,"originX",d.sceneX);
  await game.settings.set(ID,"originY",d.sceneY);
  return {sceneId:scene.id,originX:d.sceneX,originY:d.sceneY,gridSize:scene.grid.size,
    columns:Math.floor(d.sceneWidth/scene.grid.size),rows:Math.floor(d.sceneHeight/scene.grid.size)};
}

async function configure(data) {
  requireGM(); stop();
  const allowed=new Set(["bridgeURL","bridgeKey","sceneId","originX","originY"]);
  for (const [key,value] of Object.entries(data)) {
    if (!allowed.has(key)) throw new Error("Unknown configuration key");
    if (key.startsWith("origin") && !Number.isFinite(value)) throw new Error("Finite board origin required");
    if (!key.startsWith("origin") && typeof value!=="string") throw new Error("Text configuration required");
  }
  if (data.bridgeURL) loopbackURL(data.bridgeURL);
  for (const [key,value] of Object.entries(data)) await game.settings.set(ID,key,value);
}

Hooks.once("ready",()=>{
  game.modules.get(ID).api={start,stop,pair,unpair,useCurrentScene,configure,
    pairings:()=>{requireGM();return structuredClone(setting("pairings")[canvas.scene?.id] ?? {});},
    status:()=>({running,sceneId:setting("sceneId"),cursor,session,lastError,board:lastPacket ? {columns:lastPacket.columns,rows:lastPacket.rows}:null}),
    tokens:()=>{ requireGM(); return canvas.scene?.tokens.map(t=>({id:t.id,name:t.name,width:t.width,height:t.height})) ?? []; }};
  if (typeof document!=="undefined") installPanel(game.modules.get(ID).api);
});
Hooks.on("canvasTearDown",()=>stop());
