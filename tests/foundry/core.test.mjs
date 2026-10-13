import test from "node:test";
import assert from "node:assert/strict";
import {validatePacket,tokenPosition,loopbackURL} from "../../foundry/game-token-tracking/scripts/core.mjs";
const event={piece_id:"goblin",column:2,row:3,sequence:1};
const packet={protocol:1,session:"session",scene_id:"scene",columns:8,rows:8,sequence:1,events:[event]};
const geometry={size:100,originX:200,originY:200,sceneX:200,sceneY:200,sceneWidth:1000,sceneHeight:1000};
test("scene padding is included in token positions",()=>{
  assert.deepEqual(tokenPosition(event,packet,geometry,{width:1,height:1}),{x:400,y:500});
});
test("reject wrong scene and malformed coordinates",()=>{
  assert.throws(()=>validatePacket(packet,"other"));
  assert.throws(()=>validatePacket({...packet,events:[{...event,column:8}]},"scene"));
  assert.throws(()=>validatePacket({...packet,events:[{...event,row:NaN}]},"scene"));
  assert.equal(validatePacket(packet,"scene"),packet);
});
test("board and token footprints must fit",()=>{
  assert.throws(()=>tokenPosition(event,{...packet,columns:20},geometry,{width:1,height:1}));
  assert.throws(()=>tokenPosition({...event,column:9},packet,geometry,{width:2,height:1}));
});
test("custom board origin",()=>{
  assert.deepEqual(tokenPosition(event,packet,{...geometry,originX:300},{width:1,height:1}),{x:500,y:500});
});
test("bridge credentials cannot be sent to remote hosts",()=>{
  assert.equal(loopbackURL("http://127.0.0.1:8765/"),"http://127.0.0.1:8765");
  assert.throws(()=>loopbackURL("http://example.com"));
  assert.throws(()=>loopbackURL("http://localhost@evil.example"));
});
