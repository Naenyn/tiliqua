import {importScala,exportScala,MAX_SCALA_BYTES} from './scala.mjs';
import {Device} from './protocol.mjs';
import {changedSlots,writeChanges} from './sync.mjs';
import {decode,encodeScale,renameScale,renameCalibration,exportProfile,importProfile,renameConfig,exportLibrary,importLibrary,demoCalibration} from './records.mjs';
const $=id=>document.getElementById(id),banks=Array.from({length:3},()=>Array(8).fill(null)),dirty=Array.from({length:3},()=>Array(8).fill(false));
let kind=0,slot=0,device=null,busy=false,hasSnapshot=false,demo=false;
const nameDrafts=Array.from({length:3},()=>Array(8).fill(null));
const hasNameDrafts=()=>nameDrafts.some(bank=>bank.some(name=>name!==null));
const clearNameDrafts=()=>nameDrafts.forEach(bank=>bank.fill(null));
const tuningDrafts=Array(8).fill(null);
const known=Array.from({length:3},()=>Array(8).fill(false));
const kinds=["calibration","scale","config"],tabs=["Calibration","Scales","Configs"];
const names=['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'];
const message=(text,error=false)=>{$('message').textContent=text;$('message').classList.toggle('error',error);};
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function updateBulk(){
  const count=banks.reduce((n,bank,k)=>n+bank.filter((bytes,i)=>bytes&&dirty[k][i]).length,0);
  $('writeChanges').textContent=`Write changes to device${count?` (${count})`:''}`;
  $('writeChanges').disabled=!device||busy||!count||hasNameDrafts()||tuningDrafts.some(d=>d!==null);
  if(hasNameDrafts())$('backup').disabled=true;
  if(nameDrafts[kind][slot]!==null){$('write').disabled=true;$('export').disabled=true;$('exportScala').disabled=true;}
  const pending=dirty.flat().filter(Boolean).length;
  $('pendingChanges').hidden=!pending;
  $('pendingCount').textContent=`${pending} slot${pending===1?' has':'s have'} changes not written to device`;
  ['calTab','scaleTab','configTab'].forEach((id,k)=>{
    const n=dirty[k].filter(Boolean).length;
    $(id).textContent=tabs[k]+(n?` (${n})`:'');
    $(id).classList.toggle('has-changes',!!n);
    $(id).setAttribute('aria-label',tabs[k]+(n?`, ${n} slot${n===1?'':'s'} with changes not written to device`:''));
  });
  const badge=$('editor').querySelector('.badge');
  if(badge){badge.classList.toggle('pending',dirty[kind][slot]);badge.textContent=dirty[kind][slot]?'Not written to device':demo?'Demo profile':'Local snapshot';}
  $('slots').querySelectorAll('.slot').forEach((button,i)=>{
    button.classList.toggle('has-changes',dirty[kind][i]);
    button.querySelector('.pending-slot').hidden=!dirty[kind][i];
  });
}
let pendingWrites=[];
function render(){
  updateBulk();
  $('connection').textContent=device?'Connected · USB serial':demo?'Demo · local data':'Not connected';
  $('connect').hidden=!!device;$('disconnect').hidden=!device;
  $('importProfile').disabled=busy;$('importLibrary').disabled=busy;
  $('calTab').disabled=busy;$('scaleTab').disabled=busy;$('configTab').disabled=busy;
  $('read').disabled=!device||busy;$('connect').disabled=busy;$('disconnect').disabled=busy;$('demo').disabled=busy;
  $('write').disabled=nameDrafts[kind][slot]!==null||!device||(kind===2&&!device?.configsSupported)||!banks[kind][slot]||busy||(kind===1&&tuningDrafts[slot]!==null);
  $('export').disabled=!banks[kind][slot]||busy;$('exportScala').hidden=kind!==1;$('exportScala').disabled=!banks[kind][slot]||busy;$('backup').disabled=!hasSnapshot||busy||hasNameDrafts()||tuningDrafts.some(d=>d!==null);
  if(nameDrafts[kind][slot]!==null||(kind===1&&tuningDrafts[slot]!==null)){$('export').disabled=true;$('exportScala').disabled=true;}
  ['calTab','scaleTab','configTab'].forEach((id,k)=>$(id).setAttribute('aria-selected',kind===k));
  $('importProfile').accept=kind===1?'.json,.scl,application/json,text/plain':'.json,application/json';
  $('importLabel').textContent=kind===1?'Import JSON / Scala':'Import JSON';
  $('slots').replaceChildren(...banks[kind].map((bytes,i)=>{
    const button=document.createElement('button');button.className='slot'+(i===slot?' selected':'')+(dirty[kind][i]?' has-changes':'');button.disabled=busy;button.setAttribute('aria-pressed',i===slot);
    let name=known[kind][i]?'Empty slot':'Not read',detail=known[kind][i]?'Ready to import':'Connect or try a demo';
    if(bytes){try{const r=decode(bytes);name=r.name||`${kind===2?"Route config":"User scale"} ${i+1}`;detail=r.kind===2?`${r.routes.filter(r=>r.outputs.length).length} routes · ${r.routes.reduce((n,r)=>n+r.outputs.length,0)} outputs`:r.kind===0?`${r.points.length} measured points`:r.degrees?`${r.degrees.length} degrees · ${(r.period/1000).toFixed(3)} cents`:`${r.octaves} octave${r.octaves===1?'':'s'} · ${r.masks.slice(0,r.octaves).reduce((a,m)=>a+count(m),0)} intervals`;}
      catch(e){name='Invalid record';detail='Export to inspect';}}
    button.innerHTML=`<span class="number">${String(i+1).padStart(2,'0')}</span><span><strong>${escape(name)}</strong><small>${escape(detail)}</small><small class="pending-slot" ${dirty[kind][i]?'':'hidden'}>● Not written to device</small></span>`;
    button.onclick=()=>{slot=i;render();};return button;
  }));
  const bytes=banks[kind][slot];
  if(!bytes){$('editor').innerHTML=`<div class="empty"><p class="eyebrow">${kinds[kind].toUpperCase()} SLOT ${slot+1}</p><h2>${known[kind][slot]?'Empty saved slot':'Your profiles live on INTONO.'}</h2><p>${kind===0?'Import a measured calibration profile, or read your instrument.':kind===1?'Create a scale of intervals, import one, or read your instrument.':'Read your saved route configs from Intono, or import a config backup.'}</p>${kind===1?'<button id="newScale">Create a scale</button>':''}</div>`;
    if($('newScale'))$('newScale').onclick=()=>{banks[1][slot]=encodeScale({octaves:1,masks:[4095,0,0,0,0,0,0,0]});dirty[1][slot]=true;known[1][slot]=true;hasSnapshot=true;render();};return;}
  let r;try{r=decode(bytes);}catch(e){$('write').disabled=true;$('editor').innerHTML=`<h2>Invalid saved record</h2><p>${escape(e.message)}</p><p>You can export this record for inspection, or import a replacement.</p>`;return;}
  $('editor').innerHTML=`<div class="editor-head"><div><p class="eyebrow">${kinds[kind].toUpperCase()} SLOT ${slot+1}</p><h2>${escape(r.name||`${kind===2?"Route config":"User scale"} ${slot+1}`)}</h2><p>${kind===0?'Measured oscillator response':kind===1?'Intervals, ready for any root key':'All four routes · outputs start stopped'}</p></div><span class="badge${dirty[kind][slot]?' pending':''}">${dirty[kind][slot]?'Not written to device':demo?'Demo profile':'Local snapshot'}</span></div>`;
  if(kind===2){
    const preset=['Chromatic','Major','Minor','Major pentatonic','Minor pentatonic','24 EDO','Custom','Dorian','Mixolydian','Phrygian','Lydian','Harmonic minor','Melodic minor','Blues'];
    const note=n=>names[n%12]+(Math.floor(n/12)-1);
    $('editor').insertAdjacentHTML('beforeend',`<div class="fields"><label>Config name<input id="configName" type="text" maxlength="24" value="${escape(r.name||'')}" ${busy?'disabled':''}></label></div>${r.routes.map((route,i)=>`<section class="metadata"><div>Route ${i+1}<strong>${route.outputs.length?'IN'+route.input+' → '+route.outputs.map(n=>'OUT'+n).join(', '):'No outputs assigned'}</strong></div><div>MIDI transpose<strong>${route.midi.channel?'Channel '+route.midi.channel+' · base '+note(route.midi.base)+' · '+(route.midi.latch?'Latch':'Reset on release'):'Off'}</strong></div>${route.outputs.map(n=>{const c=r.channels[n];return `<div>OUT${n}<strong>${escape(c.quantize?(c.importedSlot?'Scala slot '+c.importedSlot:c.scaleSlot?'Scale slot '+c.scaleSlot:preset[c.scale]):'Unquantized')} · ${names[c.root]} · ${c.equal?'Equal':'Nearest'} · ${c.transpose>=0?'+':''}${c.transpose} st</strong><small>${c.correction===0?'Nominal CV':c.correction===1?'Calibration from RAM (not included in backup)':'Calibration slot '+(c.correction-1)} · 0 V = ${note(c.zero)}</small></div>`;}).join('')}</section>`).join('')}<p class="note">This is a saved configuration, not live route status. Restore its referenced calibration and Scala slots as well; library export includes those banks. Keyboard intervals are embedded in the config. Loading on Intono leaves outputs stopped.</p>`);
    bindName('configName',renameConfig,r.name);
  }else if(kind===0){
    $('editor').insertAdjacentHTML('beforeend',`<div class="fields"><label>Profile name<input id="profileName" type="text" maxlength="24" value="${escape(r.name)}" ${busy?'disabled':''}></label></div><div class="metadata"><div>Captured connection<strong>IN${r.input} → OUT${r.output}</strong></div><div>0 V reference<strong>${escape(names[r.zeroNote%12]+(Math.floor(r.zeroNote/12)-1))}</strong></div><div>Record version<strong>${r.version}</strong></div><div>Curve range<strong>${(r.points[0].microvolts/1e6).toFixed(2)} to ${(r.points.at(-1).microvolts/1e6).toFixed(2)} V</strong></div></div><div class="chart">${plot(r.points)}</div><p class="note">The measured points are preserved. Renaming does not change the calibration.</p>`);
    bindName('profileName',renameCalibration,r.name);
  }else if(r.degrees){
    $('editor').insertAdjacentHTML('beforeend',`<div class="metadata"><div>Scale degrees<strong>${r.degrees.length}</strong></div><div>Repeating period<strong>${(r.period/1000).toFixed(3)} cents</strong></div><div>Precision<strong>0.001 cent</strong></div></div><p class="note">Microtonal intervals are shown as cents, starting at implicit unison. The final pitch is the repeating period. Root key and mapping are configured on the route.</p><div class="fields"><label>Scala tuning<textarea id="tuningText" rows="12" ${busy?'disabled':''}>${escape(tuningDrafts[slot]??exportScala(bytes))}</textarea></label></div><button id="applyTuning" ${busy?'disabled':''}>Apply interval edits</button><p class="note">Edit the cents or ratios, then apply. No device write happens here. INTONO displays the degree count and period; use this utility to edit imported tunings.</p>`);
    $('tuningText').oninput=()=>{tuningDrafts[slot]=$('tuningText').value;dirty[1][slot]=true;updateBulk();$('write').disabled=true;$('export').disabled=true;$('exportScala').disabled=true;$('backup').disabled=true;message('Interval text edited. Apply interval edits before writing or exporting.');};
    $('applyTuning').onclick=()=>{try{const tuning=importScala($('tuningText').value).bytes;const name=decode(banks[1][slot]).name;banks[1][slot]=name?renameScale(tuning,name):tuning;dirty[1][slot]=true;tuningDrafts[slot]=null;render();message('Interval edits applied locally. Write this slot to save them on INTONO.');}catch(e){message(e.message,true);}};
  }else{
    $('editor').insertAdjacentHTML('beforeend',`<div class="fields"><label>Octaves<select id="octaves" ${busy?'disabled':''}>${Array.from({length:8},(_,i)=>`<option ${r.octaves===i+1?'selected':''}>${i+1}</option>`).join('')}</select></label><p class="legend"><b>Blue</b> keys are included. Click a key to toggle its interval.<br>Labels show intervals from the start of each octave.</p></div><div id="keyboards"></div>`);
    $('octaves').onchange=e=>{r.octaves=Number(e.target.value);saveScale(r);};
    for(let octave=0;octave<r.octaves;octave++){
      const box=document.createElement('div');box.className='octave';box.innerHTML=`<div class="octave-caption"><span>OCTAVE ${octave+1}</span><span>${count(r.masks[octave])} intervals</span></div><div class="keyboard"></div>`;
      const keyboard=box.querySelector('.keyboard'),whites=[0,2,4,5,7,9,11],blacks=[[1,1],[3,2],[6,4],[8,5],[10,6]];
      for(const [interval,black,boundary] of [...whites.map(i=>[i,false,0]),...blacks.map(([i,b])=>[i,true,b])]){
        const key=document.createElement('button'),included=!!(r.masks[octave]&(1<<interval));key.className='key'+(black?' black':'')+(included?' included':'');key.disabled=busy;
        key.setAttribute('aria-label',`Octave ${octave+1}, interval ${interval} semitones`);key.setAttribute('aria-pressed',included);key.innerHTML=`<span>${interval}</span>`;
        if(black)key.style.left=`${boundary*100/7-4}%`;
        key.onclick=()=>{r.masks[octave]^=1<<interval;saveScale(r,`Octave ${octave+1}, interval ${interval} semitones`);};keyboard.append(key);
      }$('keyboards').append(box);
    }
  }
  if(kind===1){
    $('editor').insertAdjacentHTML('beforeend',`<div class="fields"><label>Scale name<input id="scaleName" type="text" maxlength="24" value="${escape(r.name||'')}" placeholder="Name this scale" ${busy?'disabled':''}></label></div>`);
    bindName('scaleName',renameScale,r.name);
  }
}
function bindName(id,rename,name){
  const input=$(id),k=kind,s=slot;
  input.value=nameDrafts[k][s]??name??'';
  input.oninput=()=>{
    dirty[k][s]=true;nameDrafts[k][s]=input.value;
    try{
      banks[k][s]=rename(banks[k][s],input.value);nameDrafts[k][s]=null;
      input.setCustomValidity('');
      $('write').disabled=!device||busy||(k===1&&tuningDrafts[s]!==null)||(k===2&&!device?.configsSupported);
      $('export').disabled=busy||(k===1&&tuningDrafts[s]!==null);
      $('exportScala').disabled=$('export').disabled;
      $('backup').disabled=busy||hasNameDrafts()||tuningDrafts.some(d=>d!==null);
      message('Name changed locally. Write to device or export a backup to keep it.');
    }catch(error){input.setCustomValidity(error.message);message(error.message,true);}
    updateBulk();
  };
  if(nameDrafts[k][s]!==null){try{rename(banks[k][s],input.value);}catch(error){input.setCustomValidity(error.message);message(error.message,true);}}
}
function count(mask){let n=0;while(mask){n+=mask&1;mask>>>=1;}return n;}
function saveScale(r,focus){r.name=decode(banks[1][slot]).name;banks[1][slot]=r.name?renameScale(encodeScale(r),r.name):encodeScale(r);dirty[1][slot]=true;render();if(focus)document.querySelector(`[aria-label="${focus}"]`)?.focus();}
function plot(points){
  const first=points[0],last=points.at(-1),x=p=>45+(p.microvolts-first.microvolts)/(last.microvolts-first.microvolts)*500,y=p=>185-(p.millicents-first.millicents)/(last.millicents-first.millicents)*165;
  return `<svg viewBox="0 0 580 220" role="img" aria-label="Measured pitch rises with control voltage">${[0,1,2,3,4].map(i=>`<line x1="45" y1="${20+i*41.25}" x2="545" y2="${20+i*41.25}"/><line x1="${45+i*125}" y1="20" x2="${45+i*125}" y2="185"/>`).join('')}<path d="${points.map((p,i)=>(i?'L':'M')+x(p).toFixed(2)+','+y(p).toFixed(2)).join(' ')}"/><text x="45" y="205" text-anchor="middle">${(first.microvolts/1e6).toFixed(2)} V</text><text x="545" y="205" text-anchor="middle">${(last.microvolts/1e6).toFixed(2)} V</text><text x="10" y="16">Pitch</text></svg>`;
}
async function work(task){if(busy)return;busy=true;render();try{await task();}catch(e){message(e.message,true);}finally{busy=false;render();}}
async function readAll(){
  if(dirty.some(bank=>bank.some(Boolean))&&!confirm('Reading will replace your local edits. Continue?'))return;
  const next=[[],[],[]];for(let k=0;k<(device.configsSupported?3:2);k++)for(let i=0;i<8;i++){message(`Reading ${kinds[k]} slot ${i+1} of 8…`);next[k][i]=await device.read(k,i+1);}
  for(let k=0;k<3;k++){banks[k]=next[k].length?next[k]:Array(8).fill(null);dirty[k].fill(false);known[k].fill(k<2||device.configsSupported);}tuningDrafts.fill(null);clearNameDrafts();hasSnapshot=true;demo=false;message(device.configsSupported?'Read complete. All 24 saved slots are shown. Edits stay local until you write a slot.':'Profiles read. Update firmware to read saved route configs.');
}
$('connect').onclick=()=>work(async()=>{
  if(!navigator.serial)throw Error('This browser does not support Web Serial. Open the utility in desktop Chrome or Edge.');
  message('Choose Tiliqua R5 apfbug — the USB debug serial port.');
  let port;try{port=await navigator.serial.requestPort({filters:[{usbVendorId:0x1209,usbProductId:0xc0ca}]});}
  catch(e){if(e.name==='NotFoundError')throw Error('Connection canceled. Choose the Tiliqua debug serial port when ready.');throw e;}
  const candidate=new Device(port,()=>{
    if(device===candidate){device=null;message('Connection lost. Local edits are retained; reconnect to transfer profiles.',true);render();}
    // Do not await cleanup inside the reader pump itself.
    candidate.close().catch(()=>{});
  });
  try{await candidate.open();device=candidate;demo=false;message('Connected. Read from device to inspect saved profiles.');}
  catch(e){await candidate.close();throw e;}
});
$('disconnect').onclick=()=>work(async()=>{await device.close();device=null;message('Disconnected. Your local snapshot is still available to edit and export.');});
$('read').onclick=()=>work(readAll);
$('demo').onclick=()=>{
  if(dirty.some(b=>b.some(Boolean))&&!confirm('Replace your local edits with demo profiles?'))return;
  banks.forEach((_,k)=>banks[k]=Array(8).fill(null));banks[0][0]=demoCalibration();banks[1][0]=encodeScale({octaves:2,masks:[0xab5,0x295,0,0,0,0,0,0]});tuningDrafts.fill(null);clearNameDrafts();dirty.forEach(b=>b.fill(false));known.forEach(b=>b.fill(true));demo=true;hasSnapshot=true;message('Demo data. No device profiles have been changed.');render();
};
$('calTab').onclick=()=>{if(!busy){kind=0;render();}};$('scaleTab').onclick=()=>{if(!busy){kind=1;render();}};$('configTab').onclick=()=>{if(!busy){kind=2;render();}};
$('write').onclick=()=>{if(busy)return;$('confirmText').textContent=`Replace ${kinds[kind]} slot ${slot+1} on INTONO with the profile shown here?`;$('confirm').showModal();};
$('cancel').onclick=()=>$('confirm').close();
$('confirmWrite').onclick=()=>{$('confirm').close();work(async()=>{message(`Writing slot ${slot+1}…`);await device.write(kind,slot+1,banks[kind][slot]);dirty[kind][slot]=false;demo=false;message(`Slot ${slot+1} saved and verified by reading it back. Active route settings were not changed.`);});};
$('writeChanges').onclick=()=>{
  if(busy||!device||hasNameDrafts()||tuningDrafts.some(d=>d!==null))return;
  try{
    pendingWrites=changedSlots(banks,dirty);
    for(const item of pendingWrites){if(decode(item.bytes).kind!==item.kind)throw Error('Profile type does not match its slot.');device.validateWrite(item.kind,item.bytes);}
    if(!pendingWrites.length)return;
    $('bulkList').replaceChildren(...pendingWrites.map(item=>{
      const li=document.createElement('li'),name=decode(item.bytes).name;
      li.textContent=`${tabs[item.kind]} · slot ${item.slot}${name?` · ${name}`:''}`;return li;
    }));
    $('bulkTitle').textContent=`Write ${pendingWrites.length} changed slot${pendingWrites.length===1?'':'s'}?`;
    $('bulkConfirm').showModal();
  }catch(e){message(e.message,true);}
};
$('cancelBulk').onclick=()=>$('bulkConfirm').close();
$('confirmBulk').onclick=()=>{
  $('bulkConfirm').close();
  const queue=pendingWrites;pendingWrites=[];
  work(async()=>{
    const total=queue.length;
    $('writeProgress').hidden=false;$('writeProgress').max=total;$('writeProgress').value=0;
    try{
      await writeChanges(device,queue,item=>{
        dirty[item.kind][item.slot-1]=false;demo=false;
      },(completed,item)=>{
        $('writeProgress').value=completed;
        message(`Writing ${completed+1} of ${total}: ${tabs[item.kind]} slot ${item.slot}…`);
      });
      $('writeProgress').value=total;
      message(`All ${total} changed slots saved and verified. Active route settings were not changed.`);
    }catch(e){
      throw Error(`${e.message} Remaining changes are kept locally. Review the failed slot before retrying if its write status is uncertain.`);
    }finally{$('writeProgress').hidden=true;}
  });
};
function download(name,value,type='application/json'){const url=URL.createObjectURL(new Blob([type==='application/json'?JSON.stringify(value,null,2):value],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('export').onclick=()=>download(`intono-${kinds[kind]}-${slot+1}.json`,exportProfile(banks[kind][slot],kind));
$('exportScala').onclick=()=>{try{download(`intono-scale-${slot+1}.scl`,exportScala(banks[1][slot]),'text/plain');}catch(e){message(e.message,true);}};
$('backup').onclick=()=>download('intono-library.json',exportLibrary(known[2].some(Boolean)?banks:banks.slice(0,2)));
$('importProfile').onchange=e=>work(async()=>{const file=e.target.files[0];e.target.value='';if(!file)return;if(file.size>MAX_SCALA_BYTES)throw Error('Profile file exceeds the 100,000-byte limit');const text=await file.text(),scala=/\.scl$/i.test(file.name);if(scala&&kind!==1)throw Error('Choose the Scales tab before importing a Scala file.');let bytes;if(scala){const tuning=importScala(text);const name=(tuning.description||file.name.replace(/\.scl$/i,'')).replace(/[^\x20-\x7e]/g,'?').trim().slice(0,24);bytes=name?renameScale(tuning.bytes,name):tuning.bytes;}else{bytes=importProfile(JSON.parse(text));}const r=decode(bytes);
  if(r.kind!==kind)throw Error(`Choose the ${tabs[r.kind]} tab before importing this profile.`);
  if(banks[kind][slot]&&!confirm(`Replace the local copy of slot ${slot+1}?`))return;banks[kind][slot]=bytes;nameDrafts[kind][slot]=null;if(kind===1)tuningDrafts[slot]=null;dirty[kind][slot]=true;known[kind][slot]=true;hasSnapshot=true;message('Imported locally. Write this slot to save it on INTONO.');});
$('importLibrary').onchange=e=>work(async()=>{const file=e.target.files[0];e.target.value='';if(!file)return;if(file.size>200000)throw Error('Library file is too large');const value=JSON.parse(await file.text());
  const next=importLibrary(value);
  if(!confirm('Replace the local library snapshot? Device slots will not change.'))return;
  for(let k=0;k<next.length;k++){banks[k]=next[k];dirty[k]=next[k].map(Boolean);known[k].fill(true);nameDrafts[k].fill(null);}tuningDrafts.fill(null);hasSnapshot=true;demo=false;message('Library imported locally. Use Write changes to device to copy the imported profiles to INTONO. Empty slots in the file do not delete device profiles.');});
navigator.serial?.addEventListener('disconnect',event=>{if(device&&(event.target===device.port||event.port===device.port)){device.close().catch(()=>{});device=null;message('Device disconnected. Local edits and exports remain available.',true);render();}});
render();

window.addEventListener("beforeunload",event=>{if(dirty.some(bank=>bank.some(Boolean))){event.preventDefault();event.returnValue="";}});
