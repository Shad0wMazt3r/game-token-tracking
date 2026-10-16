/* Local control surface. No model or Foundry status is fabricated. */
const $ = id => document.getElementById(id);
let key = new URLSearchParams(location.hash.slice(1)).get('key') || sessionStorage.getItem('table-key') || '';
if (location.hash) history.replaceState(null, '', location.pathname);
if (key) sessionStorage.setItem('table-key', key);
let status = null, selected = '', signature = '', connected = false, frozen = false, points = [], previewImage = null, polling = false, busy = false, initialized = false;
const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
function notify(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(notify.timer); notify.timer = setTimeout(() => $('toast').hidden = true, 7000); }
async function request(path, data, blob = false) {
  const response = await fetch(path, { method: data === undefined ? 'GET' : 'POST', headers: { Authorization: 'Bearer ' + key, ...(data === undefined ? {} : { 'Content-Type': 'application/json' }) }, body: data === undefined ? undefined : JSON.stringify(data), signal: AbortSignal.timeout(15000) });
  if (!response.ok) { let message = 'Request failed: ' + response.status; try { message = (await response.json()).error || message; } catch {} throw new Error(message); }
  return blob ? response.blob() : response.json();
}
async function act(action) { if (busy) return; busy = true; try { await action(); await refresh(); } catch (error) { notify(error.message); } finally { busy = false; } }
function connection(ok) { connected = ok; $('connection').textContent = ok ? 'Bridge connected' : 'Disconnected'; $('connection').classList.toggle('online', ok); $('auth').hidden = ok; for (const id of ['start','pause','resync','save-inventory','open-cameras','load-weights','freeze','save-calibration']) $(id).disabled = !ok; }
async function refresh() {
  if (polling) return; polling = true;
  try { status = await request('/api/status'); connection(true); render(); }
  catch (error) { connection(false); $('run-state').textContent = 'Unavailable'; $('notice').textContent = 'Connection lost. Reconnect before sending movements. ' + error.message; }
  finally { polling = false; }
}
function render() {
  const s = status;
  if (!initialized) { $('references').value = JSON.stringify([[0,0],[s.columns,0],[s.columns,s.rows],[0,s.rows]]); $('inventory').value=s.pieces.join('\n'); initialized=true; }
  $('scene').textContent = s.scene_id; $('dimensions').textContent = s.columns + ' columns · ' + s.rows + ' rows';
  $('board-size').textContent = s.columns + ' × ' + s.rows; $('piece-count').textContent = s.pieces.length;
  $('run-state').textContent = s.running ? 'Running' : 'Paused'; $('start').textContent = s.mode === 'simulation' ? 'Start simulation' : 'Start tracking';
  $('start').disabled = s.running; $('pause').disabled = !s.running;
  $('save-inventory').disabled = s.mode !== 'simulation';
  $('simulation-tab').setAttribute('aria-pressed', s.mode === 'simulation'); $('camera-tab').setAttribute('aria-pressed', s.mode === 'camera');
  $('camera-tools').hidden = s.mode !== 'camera';
  $('notice').textContent = s.error || (s.mode === 'simulation' ? 'Simulation sends real bridge events. Start the Foundry module before moving pieces.' : 'Camera mode uses custom miniature weights. Freeze and calibrate every view before starting.');
  $('board-hint').textContent = s.mode === 'simulation' ? 'Select a piece, then choose a square. Or drag a piece onto the board.' : 'Confirmed board positions appear here. Manual simulation moves are disabled in camera mode.';
  const sig = JSON.stringify([s.columns,s.rows,s.pieces,s.confirmed,s.mode,s.running,selected]);
  if (sig !== signature) { signature = sig; renderBoard(); }
  const rows = s.history.map(e => { const tr = node('tr'); [e.piece_id, e.column + ', ' + e.row, e.source, 'Bridge accepted', '#' + e.sequence].forEach((v,i) => tr.append(node('td',v,i===3?'delivery':''))); return tr; });
  if (rows.length) $('history').replaceChildren(...rows); else { const tr=node('tr'),td=node('td','No movements yet. Start simulation and place a piece.','empty');td.colSpan=5;tr.append(td);$('history').replaceChildren(tr); }
  $('camera-diagnostics').textContent = s.cameras.map(c => 'Camera '+(Number(c.id)+1)+' · '+(c.calibrated?'calibrated':'needs calibration')+(c.age_ms!==undefined?' · frame age '+c.age_ms+' ms':'')+(c.inference_ms!==undefined?' · inference '+c.inference_ms+' ms':'')+(c.calibration_status?' · '+c.calibration_status:'')+(c.error?' · '+c.error:'')).join('\n') + (s.diagnostics.fusion ? '\nUsable: '+s.diagnostics.fusion.usable+' · Ambiguous: '+(s.diagnostics.fusion.ambiguous.join(', ')||'none') : '');
}
function token(piece) { const index=status.pieces.indexOf(piece), t=node('span',String(index+1),'token color-'+index%3); t.title=piece; return t; }
function renderBoard() {
  if (!status.pieces.includes(selected)) selected = status.pieces[0] || '';
  $('board').style.setProperty('--columns', status.columns);
  const cells=[];
  for(let row=0;row<status.rows;row++) for(let column=0;column<status.columns;column++) {
    const cell=node('button',undefined,'cell'); cell.type='button';cell.setAttribute('aria-label','Column '+column+', row '+row);cell.dataset.column=column;cell.dataset.row=row;cell.append(node('span',column+','+row,'coord'));
    const occupants=Object.entries(status.confirmed).filter(([,pos])=>pos[0]===column&&pos[1]===row);
    for(const [piece] of occupants)cell.append(token(piece));
    cell.addEventListener('click',()=>move(selected,column,row));
    cell.addEventListener('dragover',e=>{e.preventDefault();cell.classList.add('dragover');});cell.addEventListener('dragleave',()=>cell.classList.remove('dragover'));
    cell.addEventListener('drop',e=>{e.preventDefault();cell.classList.remove('dragover');move(e.dataTransfer.getData('text/plain'),column,row);});
    cells.push(cell);
  }
  $('board').replaceChildren(...cells);
  $('pieces').replaceChildren(...status.pieces.map(piece=>{const button=node('button',undefined,'piece');button.type='button';button.draggable=true;button.setAttribute('aria-pressed',piece===selected);button.append(token(piece));const info=node('span',undefined,'piece-info');info.append(node('strong',piece),node('small',status.confirmed[piece]?'Square '+status.confirmed[piece].join(', '):'No confirmed position'));button.append(info);button.addEventListener('click',()=>{selected=piece;signature='';render();});button.addEventListener('dragstart',e=>{e.dataTransfer.setData('text/plain',piece);});return button;}));
}
function move(piece,column,row) { if (!connected||status.mode!=='simulation'||!status.running) { notify('Start simulation before placing pieces.'); return; } act(()=>request('/api/move',{piece_id:piece,column,row})); }
function control(action, extra={}) { return request('/api/control',{action,...extra}); }
$('auth-form').addEventListener('submit',event=>{event.preventDefault();key=$('key').value;sessionStorage.setItem('table-key',key);refresh();});
$('connection-button').addEventListener('click',()=>{$('auth').hidden=!$('auth').hidden;if(!$('auth').hidden)$('key').focus();});
$('simulation-tab').addEventListener('click',()=>act(()=>control('mode',{mode:'simulation'})));
$('camera-tab').addEventListener('click',()=>act(()=>control('mode',{mode:'camera'})));
$('start').addEventListener('click',()=>act(()=>control('start')));$('pause').addEventListener('click',()=>act(()=>control('pause')));$('resync').addEventListener('click',()=>act(()=>control('resync')));
$('save-inventory').addEventListener('click',()=>act(()=>control('inventory',{pieces:$('inventory').value.split('\n').map(x=>x.trim()).filter(Boolean)})));
$('export').addEventListener('click',()=>{if(!status)return;const link=node('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(status.history,null,2)],{type:'application/json'}));link.download='recent-movements.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);});
$('open-cameras').addEventListener('click',()=>act(async()=>{const sources=$('sources').value.split(',').map(x=>x.trim());if(sources.some(x=>!/^\d+$/.test(x)))throw Error('Enter one or two webcam indices, separated by a comma.');await request('/api/cameras',{cameras:sources.map(x=>({source:Number(x)}))});frozen=false;points=[];await preview();}));
$('load-weights').addEventListener('click',()=>act(()=>request('/api/weights',{path:$('weights').value})));
async function showImage(blob) { const image=await createImageBitmap(blob);previewImage?.close();previewImage=image;$('preview').width=image.width;$('preview').height=image.height;$('preview-empty').hidden=true;drawPreview(); }
async function preview() { if(frozen||!connected||status?.mode!=='camera'||!status.cameras.length)return;try{await showImage(await request('/api/frame?camera='+$('camera-select').value,undefined,true));}catch(error){$('calibration-result').textContent=error.message;} }
function references(){const r=JSON.parse($('references').value);if(!Array.isArray(r)||r.length<4||r.some(p=>!Array.isArray(p)||p.length!==2||p.some(v=>!Number.isFinite(v))))throw Error('Enter at least four finite [x,y] board intersections.');return r;}
function drawPreview(){if(!previewImage)return;const canvas=$('preview'),ctx=canvas.getContext('2d');ctx.drawImage(previewImage,0,0);ctx.font='18px sans-serif';points.forEach(([x,y],i)=>{ctx.beginPath();ctx.fillStyle='#b8efcf';ctx.arc(x,y,6,0,Math.PI*2);ctx.fill();ctx.fillText(String(i+1),x+10,y-10);});}
$('freeze').addEventListener('click',()=>act(async()=>{await showImage(await request('/api/freeze',{camera:$('camera-select').value},true));frozen=true;points=[];references();$('calibration-hint').textContent='Click reference 1: '+JSON.stringify(references()[0]);drawPreview();}));
$('camera-select').addEventListener('change',()=>{frozen=false;points=[];previewImage?.close();previewImage=null;const c=$('preview');c.getContext('2d').clearRect(0,0,c.width,c.height);$('preview-empty').hidden=false;$('calibration-result').textContent='';preview();});
$('references').addEventListener('input',()=>{points=[];drawPreview();});
$('preview').addEventListener('click',event=>{if(!frozen){notify('Freeze a frame before choosing references.');return;}try{const refs=references();if(points.length>=refs.length)return;const rect=$('preview').getBoundingClientRect();points.push([(event.clientX-rect.left)*$('preview').width/rect.width,(event.clientY-rect.top)*$('preview').height/rect.height]);drawPreview();$('calibration-hint').textContent=points.length<refs.length?'Click reference '+(points.length+1)+': '+JSON.stringify(refs[points.length]):'All references selected. Save calibration.';}catch(error){notify(error.message);}});
$('clear-points').addEventListener('click',()=>{points=[];drawPreview();$('calibration-hint').textContent='Points reset. Click references in the listed order.';});
$('save-calibration').addEventListener('click',()=>act(async()=>{const refs=references();if(points.length!==refs.length)throw Error('Select every board reference before saving.');const result=await request('/api/calibrate',{camera:$('camera-select').value,image_points:points,board_points:refs});$('calibration-result').textContent='Saved · fit residual '+result.residual_cells.toFixed(3)+' cells. Verify unused intersections before tracking.';frozen=false;}));
connection(false);if(key)refresh();setInterval(()=>{if(key)refresh();},1000);setInterval(preview,1500);
