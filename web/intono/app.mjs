import {Device} from './protocol.mjs';
import {decode,encodeScale,renameCalibration,exportProfile,importProfile,demoCalibration} from './records.mjs';
const $=id=>document.getElementById(id),banks=[Array(8).fill(null),Array(8).fill(null)],dirty=[Array(8).fill(false),Array(8).fill(false)];
let kind=0,slot=0,device=null,busy=false,hasSnapshot=false,demo=false;
const known=[Array(8).fill(false),Array(8).fill(false)];
const names=['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'];
const message=(text,error=false)=>{$('message').textContent=text;$('message').classList.toggle('error',error);};
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function render(){
  $('connection').textContent=device?'Connected · USB serial':demo?'Demo · local data':'Not connected';
  $('connect').hidden=!!device;$('disconnect').hidden=!device;
  $('read').disabled=!device||busy;$('connect').disabled=busy;$('disconnect').disabled=busy;$('demo').disabled=busy;
  $('write').disabled=!device||!banks[kind][slot]||busy;
  $('export').disabled=!banks[kind][slot]||busy;$('backup').disabled=!hasSnapshot||busy;
  $('calTab').setAttribute('aria-selected',kind===0);$('scaleTab').setAttribute('aria-selected',kind===1);
  $('slots').replaceChildren(...banks[kind].map((bytes,i)=>{
    const button=document.createElement('button');button.className='slot'+(i===slot?' selected':'');button.disabled=busy;button.setAttribute('aria-pressed',i===slot);
    let name=known[kind][i]?'Empty slot':'Not read',detail=known[kind][i]?'Ready to import':'Connect or try a demo';
    if(bytes){try{const r=decode(bytes);name=r.kind===0?r.name:`User scale ${i+1}`;detail=r.kind===0?`${r.points.length} measured points`:`${r.octaves} octave${r.octaves===1?'':'s'} · ${r.masks.slice(0,r.octaves).reduce((a,m)=>a+count(m),0)} intervals`;}
      catch(e){name='Invalid record';detail='Export to inspect';}}
    button.innerHTML=`<span class="number">${String(i+1).padStart(2,'0')}</span><span><strong>${escape(name)}</strong><small>${escape(detail)}</small></span>${dirty[kind][i]?'<span class="dirty-dot" title="Local changes">●</span>':''}`;
    button.onclick=()=>{slot=i;render();};return button;
  }));
  const bytes=banks[kind][slot];
  if(!bytes){$('editor').innerHTML=`<div class="empty"><p class="eyebrow">${kind===0?'CALIBRATION':'SCALE'} SLOT ${slot+1}</p><h2>${known[kind][slot]?'Empty saved slot':'Your profiles live on INTONO.'}</h2><p>${kind===0?'Import a measured calibration profile, or read your instrument.':'Create a scale of intervals, import one, or read your instrument.'}</p>${kind===1?'<button id="newScale">Create a scale</button>':''}</div>`;
    if($('newScale'))$('newScale').onclick=()=>{banks[1][slot]=encodeScale({octaves:1,masks:[4095,0,0,0,0,0,0,0]});dirty[1][slot]=true;known[1][slot]=true;hasSnapshot=true;render();};return;}
  let r;try{r=decode(bytes);}catch(e){$('editor').innerHTML=`<h2>Invalid saved record</h2><p>${escape(e.message)}</p><p>You can export this record for inspection, or import a replacement.</p>`;return;}
  $('editor').innerHTML=`<div class="editor-head"><div><p class="eyebrow">${kind===0?'CALIBRATION':'SCALE'} SLOT ${slot+1}</p><h2>${escape(kind===0?r.name:`User scale ${slot+1}`)}</h2><p>${kind===0?'Measured oscillator response':'Intervals, ready for any root key'}</p></div><span class="badge">${dirty[kind][slot]?'Local changes':demo?'Demo profile':'Local snapshot'}</span></div>`;
  if(kind===0){
    $('editor').insertAdjacentHTML('beforeend',`<div class="fields"><label>Profile name<input id="profileName" type="text" maxlength="24" value="${escape(r.name)}" ${busy?'disabled':''}></label></div><div class="metadata"><div>Captured connection<strong>IN${r.input} → OUT${r.output}</strong></div><div>0 V reference<strong>${escape(names[r.zeroNote%12]+(Math.floor(r.zeroNote/12)-1))}</strong></div><div>Record version<strong>${r.version}</strong></div><div>Curve range<strong>${(r.points[0].microvolts/1e6).toFixed(2)} to ${(r.points.at(-1).microvolts/1e6).toFixed(2)} V</strong></div></div><div class="chart">${plot(r.points)}</div><p class="note">The measured points are preserved. Renaming does not change the calibration.</p>`);
    $('profileName').onchange=e=>{try{banks[0][slot]=renameCalibration(bytes,e.target.value);dirty[0][slot]=true;render();}catch(error){message(error.message,true);e.target.value=r.name;}};
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
        key.onclick=()=>{r.masks[octave]^=1<<interval;saveScale(r);};keyboard.append(key);
      }$('keyboards').append(box);
    }
  }
}
function count(mask){let n=0;while(mask){n+=mask&1;mask>>>=1;}return n;}
function saveScale(r){banks[1][slot]=encodeScale(r);dirty[1][slot]=true;render();}
function plot(points){
  const first=points[0],last=points.at(-1),x=p=>45+(p.microvolts-first.microvolts)/(last.microvolts-first.microvolts)*500,y=p=>185-(p.millicents-first.millicents)/(last.millicents-first.millicents)*165;
  return `<svg viewBox="0 0 580 220" role="img" aria-label="Measured pitch rises with control voltage">${[0,1,2,3,4].map(i=>`<line x1="45" y1="${20+i*41.25}" x2="545" y2="${20+i*41.25}"/><line x1="${45+i*125}" y1="20" x2="${45+i*125}" y2="185"/>`).join('')}<path d="${points.map((p,i)=>(i?'L':'M')+x(p).toFixed(2)+','+y(p).toFixed(2)).join(' ')}"/><text x="45" y="205" text-anchor="middle">${(first.microvolts/1e6).toFixed(2)} V</text><text x="545" y="205" text-anchor="middle">${(last.microvolts/1e6).toFixed(2)} V</text><text x="10" y="16">Pitch</text></svg>`;
}
async function work(task){if(busy)return;busy=true;render();try{await task();}catch(e){message(e.message,true);}finally{busy=false;render();}}
async function readAll(){
  if(dirty.some(bank=>bank.some(Boolean))&&!confirm('Reading will replace your local edits. Continue?'))return;
  const next=[[],[]];for(let k=0;k<2;k++)for(let i=0;i<8;i++){message(`Reading ${k===0?'calibration':'scale'} slot ${i+1} of 8…`);next[k][i]=await device.read(k,i+1);}
  for(let k=0;k<2;k++){banks[k]=next[k];dirty[k].fill(false);known[k].fill(true);}hasSnapshot=true;demo=false;message('Read complete. All sixteen saved slots are shown. Edits stay local until you write a slot.');
}
$('connect').onclick=()=>work(async()=>{
  if(!navigator.serial)throw Error('This browser does not support Web Serial. Open the utility in desktop Chrome or Edge.');
  const port=await navigator.serial.requestPort();const candidate=new Device(port);
  try{await candidate.open();device=candidate;demo=false;message('Connected. Read from device to inspect saved profiles.');}
  catch(e){await candidate.close();throw e;}
});
$('disconnect').onclick=()=>work(async()=>{await device.close();device=null;message('Disconnected. Your local snapshot is still available to edit and export.');});
$('read').onclick=()=>work(readAll);
$('demo').onclick=()=>{
  if(dirty.some(b=>b.some(Boolean))&&!confirm('Replace your local edits with demo profiles?'))return;
  banks[0]=Array(8).fill(null);banks[1]=Array(8).fill(null);banks[0][0]=demoCalibration();banks[1][0]=encodeScale({octaves:2,masks:[0xab5,0x295,0,0,0,0,0,0]});dirty.forEach(b=>b.fill(false));known.forEach(b=>b.fill(true));demo=true;hasSnapshot=true;message('Demo data. No device profiles have been changed.');render();
};
$('calTab').onclick=()=>{if(!busy){kind=0;render();}};$('scaleTab').onclick=()=>{if(!busy){kind=1;render();}};
$('write').onclick=()=>{if(busy)return;$('confirmText').textContent=`Replace ${kind===0?'calibration':'scale'} slot ${slot+1} on INTONO with the profile shown here?`;$('confirm').showModal();};
$('cancel').onclick=()=>$('confirm').close();
$('confirmWrite').onclick=()=>{$('confirm').close();work(async()=>{message(`Writing slot ${slot+1}…`);await device.write(kind,slot+1,banks[kind][slot]);dirty[kind][slot]=false;demo=false;message(`Slot ${slot+1} saved and verified by reading it back. Active route settings were not changed.`);});};
function download(name,value){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('export').onclick=()=>download(`intono-${kind===0?'calibration':'scale'}-${slot+1}.json`,exportProfile(banks[kind][slot]));
$('backup').onclick=()=>download('intono-library.json',{format:'intono-library',version:1,banks:banks.map(bank=>bank.map(b=>b?exportProfile(b):null))});
$('importProfile').onchange=e=>work(async()=>{const file=e.target.files[0];e.target.value='';if(!file)return;if(file.size>100000)throw Error('Profile file is too large');const bytes=importProfile(JSON.parse(await file.text())),r=decode(bytes);
  if(r.kind!==kind)throw Error(`Choose the ${r.kind===0?'Calibration':'Scales'} tab before importing this profile.`);
  if(banks[kind][slot]&&!confirm(`Replace the local copy of slot ${slot+1}?`))return;banks[kind][slot]=bytes;dirty[kind][slot]=true;known[kind][slot]=true;hasSnapshot=true;message('Imported locally. Write this slot to save it on INTONO.');});
$('importLibrary').onchange=e=>work(async()=>{const file=e.target.files[0];e.target.value='';if(!file)return;if(file.size>200000)throw Error('Library file is too large');const value=JSON.parse(await file.text());
  if(value.format!=='intono-library'||value.version!==1||!Array.isArray(value.banks)||value.banks.length!==2||value.banks.some(b=>!Array.isArray(b)||b.length!==8))throw Error('Invalid INTONO library');
  const next=value.banks.map((b,k)=>b.map(p=>{if(!p)return null;const bytes=importProfile(p);if(decode(bytes).kind!==k)throw Error('Profile is in the wrong bank');return bytes;}));
  if(!confirm('Replace the local library snapshot? Device slots will not change.'))return;
  for(let k=0;k<2;k++){banks[k]=next[k];dirty[k]=next[k].map(Boolean);known[k].fill(true);}hasSnapshot=true;demo=false;message('Library imported locally. Write individual slots to copy them to INTONO. Empty slots in the file do not delete device profiles.');});
navigator.serial?.addEventListener('disconnect',event=>{if(device&&(event.target===device.port||event.port===device.port)){device.close().catch(()=>{});device=null;message('Device disconnected. Local edits and exports remain available.',true);render();}});
render();
