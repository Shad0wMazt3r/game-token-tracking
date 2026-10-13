/** Small GM control panel without reliance on Foundry application internals. */
export function installPanel(api) {
  if (!game.user.isGM) return;
  let panel=null;
  const element=(tag,text="")=>{const node=document.createElement(tag);node.textContent=text;return node;};
  function open() {
    if(panel?.isConnected) { panel.focus(); return; }
    panel=element("dialog"); panel.className="gtt-panel";
    panel.append(element("h2","Game Token Tracking"));
    const status=element("p");panel.append(status);
    const form=element("form");panel.append(form);
    const inputs={};
    for(const [key,label,type] of [["bridgeURL","Bridge URL","url"],["bridgeKey","Bridge token","password"],["sceneId","Target scene ID","text"],["originX","Board origin X (pixels)","number"],["originY","Board origin Y (pixels)","number"]]) {
      const field=element("label",label); const input=element("input");input.type=type;input.name=key;input.value=game.settings.get("game-token-tracking",key);inputs[key]=input;field.append(input);form.append(field);
    }
    form.addEventListener("submit",event=>event.preventDefault());
    const feedback=element("p");feedback.className="gtt-feedback";panel.append(feedback);
    const perform=action=>async()=>{try{feedback.textContent="";await action();render();}catch(error){feedback.textContent=error.message;}};
    const button=(label,action,parent=panel)=>{const b=element("button",label);b.type="button";b.addEventListener("click",perform(action));parent.append(b);return b;};
    button("Save connection",async()=>{const data={};for(const [key,input] of Object.entries(inputs))data[key]=input.type==="number" ? Number(input.value):input.value;await api.configure(data);},form);
    button("Use current scene",async()=>{await api.useCurrentScene();for(const [key,input] of Object.entries(inputs))input.value=game.settings.get("game-token-tracking",key);});
    const pairLabel=element("label","Physical piece ID (YOLO class name)");const piece=element("input");piece.type="text";pairLabel.append(piece);panel.append(pairLabel);
    button("Pair with selected token",async()=>{if(canvas.tokens.controlled.length!==1)throw new Error("Select exactly one token on the canvas first");await api.pair(piece.value.trim());});
    const pairings=element("select");panel.append(pairings);
    button("Remove selected pairing",()=>api.unpair(pairings.value));
    const actions=element("div");actions.className="gtt-actions";panel.append(actions);
    button("Start",()=>api.start(),actions);button("Stop",()=>api.stop(),actions);
    const hint=element("p","Select a token on the canvas, enter its physical piece ID, then pair it. Pairing/configuration changes stop tracking.");hint.className="gtt-hint";panel.append(hint);
    let interval;
    const close=()=>{clearInterval(interval);panel?.close();panel?.remove();panel=null;};
    button("Close",close);
    panel.addEventListener("cancel",event=>{event.preventDefault();close();});
    function render(){
      if(!panel) return;
      const state=api.status();status.textContent=(state.running?"Tracking":"Stopped")+" | "+(state.board ? state.board.columns+" × "+state.board.rows:"Board not connected")+(state.lastError?" | "+state.lastError:"");
      const selected=pairings.value;pairings.replaceChildren();
      for(const [physical,tokenId] of Object.entries(api.pairings())) {
        const option=element("option",physical+" → "+(canvas.scene?.tokens.get(tokenId)?.name ?? tokenId));option.value=physical;pairings.append(option);
      }
      if([...pairings.options].some(o=>o.value===selected))pairings.value=selected;
    }
    document.body.append(panel);panel.show();render();interval=setInterval(render,500);
  }
  api.openPanel=open;
  const launcher=element("button","Token Tracker");launcher.className="gtt-launcher";launcher.addEventListener("click",open);document.body.append(launcher);
}
