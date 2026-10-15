/** Non-modal, keyboard-accessible GM control surface. */
export function installPanel(api) {
  if (!game.user.isGM) return;
  let panel = null;
  const el = (tag, text, cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  function open() {
    if (panel?.isConnected) {panel.focus();return;}
    panel=el("dialog",undefined,"gtt-panel");panel.setAttribute("aria-label","Game Token Tracking");panel.tabIndex=-1;
    const top=el("div",undefined,"gtt-top");top.append(el("span","TABLE / FOUNDRY","gtt-kicker"));panel.append(top);
    panel.append(el("h2","Bring the table to life."));
    panel.append(el("p","Pair physical pieces with scene tokens. Keep control of every move.","gtt-hint"));
    const status=el("div",undefined,"gtt-status");panel.append(status);
    const feedback=el("p","","gtt-feedback");feedback.setAttribute("role","alert");panel.append(feedback);
    const perform=action=>async()=>{try{feedback.textContent="";await action();render();}catch(error){feedback.textContent=error.message;}};
    const button=(label,action,parent,primary=false)=>{const b=el("button",label,primary?"gtt-primary":"");b.type="button";b.addEventListener("click",perform(action));parent.append(b);return b;};
    const controls=el("div",undefined,"gtt-actions");panel.append(controls);
    const start=button("Start sync",()=>api.start(),controls,true);
    const stop=button("Stop sync",()=>api.stop(),controls);
    button("Check bridge",async()=>{const r=await api.checkConnection();feedback.textContent="Bridge ready · "+r.columns+" × "+r.rows+". This check did not start synchronization.";},controls);
    const connection=el("details");panel.append(connection);connection.open=!game.settings.get("game-token-tracking","bridgeKey");
    connection.append(el("summary","1 / Connection & scene"));
    const form=el("form");form.addEventListener("submit",e=>e.preventDefault());connection.append(form);
    const inputs={};
    for(const [key,label,type] of [["bridgeURL","Local bridge URL","url"],["bridgeKey","Bridge key","password"],["sceneId","Target scene ID","text"],["originX","Board origin X · pixels","number"],["originY","Board origin Y · pixels","number"]]) {
      const field=el("label",label),input=el("input");input.type=type;input.autocomplete="off";input.name=key;
      input.value=game.settings.get("game-token-tracking",key);inputs[key]=input;field.append(input);form.append(field);
    }
    button("Save connection",async()=>{const data={};for(const [key,input] of Object.entries(inputs))data[key]=input.type==="number"?Number(input.value):input.value;await api.configure(data);},form);
    button("Use viewed scene",async()=>{await api.useCurrentScene();for(const [key,input] of Object.entries(inputs))input.value=game.settings.get("game-token-tracking",key);},connection);
    connection.append(el("p","The board origin is the top-left of your physical board region on this map. Saving stops sync.","gtt-hint"));
    const pairing=el("section",undefined,"gtt-section");pairing.append(el("h3","2 / Pair your pieces"));panel.append(pairing);
    const pairLabel=el("label","Physical piece ID"),piece=el("input");piece.placeholder="goblin_1";pairLabel.append(piece);pairing.append(pairLabel);
    const selection=el("p","","gtt-hint");pairing.append(selection);
    const pairButton=button("Pair with selected token",()=>api.pair(piece.value.trim()),pairing,true);
    const list=el("div",undefined,"gtt-pairings");pairing.append(list);
    const recent=el("section",undefined,"gtt-section");recent.append(el("h3","3 / Applied movements"));panel.append(recent);
    const history=el("div",undefined,"gtt-history");recent.append(history);
    recent.append(el("p","Applied means the token document update resolved. Bridge round-trip is not camera-to-token latency.","gtt-hint"));
    let interval;
    const close=()=>{clearInterval(interval);panel?.close();panel?.remove();panel=null;launcher.focus();};
    button("Close panel",close,panel);
    panel.addEventListener("cancel",event=>{event.preventDefault();close();});
    let signature="";
    function render() {
      if(!panel)return;
      const state=api.status(),active=canvas.scene?.id===state.sceneId;
      const age=state.lastPollAt?Math.floor((Date.now()-state.lastPollAt)/1000):null;
      status.textContent=(state.running?"SYNCING":"STOPPED")+" · "+(state.board?state.board.columns+" × "+state.board.rows:"Bridge unchecked")+(state.pollMs!==null?" · request "+state.pollMs+" ms":"")+(age!==null?" · checked "+age+"s ago":"");
      status.dataset.running=String(state.running);
      start.disabled=state.running||!active;stop.disabled=!state.running;
      if(state.lastError)feedback.textContent=state.lastError;
      const selected=canvas.tokens.controlled;
      selection.textContent=!active?"View the target scene before pairing.":selected.length===1?"Selected: "+selected[0].document.name:"Select exactly one placed token on the map.";
      pairButton.disabled=!active||selected.length!==1;
      const mappings=api.pairings(),tokens=api.tokens();
      const sig=JSON.stringify([mappings,tokens.map(t=>[t.id,t.name,t.texture]),state.applied]);
      if(sig===signature)return;signature=sig;
      list.replaceChildren();
      for(const [physical,tokenId] of Object.entries(mappings)) {
        const token=tokens.find(t=>t.id===tokenId),row=el("div",undefined,"gtt-pair-row");
        if(token?.texture){const image=el("img");image.src=token.texture;image.alt="";row.append(image);}
        const text=el("div");text.append(el("strong",physical),el("span",token?.name??"Missing token"));row.append(text);
        const remove=button("Remove",()=>api.unpair(physical),row);remove.setAttribute("aria-label","Remove pairing for "+physical);list.append(row);
      }
      if(!Object.keys(mappings).length)list.append(el("p","No pairings in this scene yet.","gtt-hint"));
      history.replaceChildren(...(state.applied??[]).filter(item=>item.sceneId===canvas.scene?.id).slice(0,8).map(item=>{const row=el("div",undefined,"gtt-history-row");row.append(el("strong",item.pieceId),el("span",item.column+", "+item.row+" · #"+item.sequence));return row;}));
      if(!history.children.length)history.append(el("p","No applied movements in this browser session. Start sync, then send a fresh move.","gtt-hint"));
    }
    document.body.append(panel);panel.show();render();panel.focus();interval=setInterval(render,500);
  }
  api.openPanel=open;
  const launcher=el("button","Token Tracker","gtt-launcher");launcher.addEventListener("click",open);document.body.append(launcher);
}
