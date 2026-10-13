import test from "node:test";
import assert from "node:assert/strict";
const once=new Map(),hooks=new Map(),values=new Map();
const warnings=[],updates=[];
let packet,failUpdate=false;
const token={id:"token",name:"Goblin",x:0,y:0,width:1,height:1,async update(position){
  if(failUpdate) throw new Error("simulated update failure");
  updates.push(position); Object.assign(this,position);
}};
const scene={id:"scene",grid:{type:1,size:100},dimensions:{sceneX:200,sceneY:200,sceneWidth:1200,sceneHeight:800},tokens:new Map([["token",token]])};
scene.tokens.map=fn=>[...scene.tokens.values()].map(fn);
const moduleRecord={};
globalThis.Hooks={once:(name,fn)=>once.set(name,fn),on:(name,fn)=>hooks.set(name,fn)};
globalThis.CONST={GRID_TYPES:{SQUARE:1}};
globalThis.game={user:{isGM:true},modules:new Map([["game-token-tracking",moduleRecord]]),settings:{
 register:(id,key,data)=>values.set(key,data.default),get:(id,key)=>values.get(key),
 set:async(id,key,value)=>{values.set(key,value);return value;}
}};
globalThis.canvas={ready:true,scene,tokens:{controlled:[{document:token}]}};
globalThis.ui={notifications:{warn:message=>warnings.push(message),info:()=>{}}};
globalThis.fetch=async()=>({ok:true,json:async()=>structuredClone(packet)});
await import("../../foundry/game-token-tracking/scripts/module.mjs");
once.get("init")(); once.get("ready")();
const api=moduleRecord.api;
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const pause=()=>new Promise(resolve=>setTimeout(resolve,140));

test("GM setup, pairing, movement retries, bridge restart and scene guard",async()=>{
 const info=await api.useCurrentScene();
 assert.equal(info.sceneId,"scene"); assert.equal(info.originX,200);
 values.set("bridgeKey","test-token-at-least-16-characters");
 await api.pair("goblin");
 packet={protocol:1,session:"one",scene_id:"scene",columns:12,rows:8,sequence:0,events:[]};
 await api.start(); await flush();
 failUpdate=true;
 packet={...packet,sequence:1,events:[{piece_id:"goblin",column:2,row:3,sequence:1}]};
 await pause();
 assert.equal(api.status().cursor,0);
 assert.ok(warnings.some(message=>message.includes("simulated update failure")));
 failUpdate=false; await pause();
 assert.deepEqual(updates.at(-1),{x:400,y:500});
 assert.equal(api.status().cursor,1);
 packet={...packet,session:"two",sequence:1,events:[{piece_id:"goblin",column:4,row:1,sequence:1}]};
 await pause();
 assert.deepEqual(updates.at(-1),{x:600,y:300});
 canvas.scene={...scene,id:"other"}; await pause();
 assert.equal(api.status().running,false);
 canvas.scene=scene;
 game.user.isGM=false;
 await assert.rejects(api.start(),/GM required/);
 await assert.rejects(api.pair("other"),/GM required/);
 api.stop();
});
