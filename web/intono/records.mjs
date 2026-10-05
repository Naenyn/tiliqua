// Saved scales contain intervals, never a root key. Calibration units are
// signed microvolts and millicents, matching the firmware's versioned codecs.
export function crc32(bytes){let c=0xffffffff;for(const b of bytes){c^=b;for(let i=0;i<8;i++)c=(c>>>1)^((c&1)?0xedb88320:0);}return (~c)>>>0;}
function finish(b){new DataView(b.buffer,b.byteOffset,b.byteLength).setUint32(b.length-4,crc32(b.subarray(0,-4)),true);return b;}
export function decode(bytes){
  const b=new Uint8Array(bytes),v=new DataView(b.buffer),magic=String.fromCharCode(...b.subarray(0,4));
  if(b.length<8||v.getUint32(b.length-4,true)!==crc32(b.subarray(0,-4)))throw Error('Profile checksum does not match');
  if(magic==='TSN1'||magic==='TCN1'){
    if(b.length<48||b[4]<1||b[4]>24||b.subarray(5,8).some(x=>x!==0)||b.subarray(8+b[4],32).some(x=>x!==0))throw Error('Invalid named scale header');
    const name=String.fromCharCode(...b.subarray(8,8+b[4]));validateName(name);
    const inner=b.subarray(32,-4);if(['TSN1','TCN1'].includes(String.fromCharCode(...inner.subarray(0,4))))throw Error('Nested scale names are not supported');
    const scale=decode(inner);if(scale.kind!==(magic==='TSN1'?1:2))throw Error('Name envelope does not match record type');return {...scale,name};
  }
  if(/^TQS[1-6]$/.test(magic))return decodeConfig(b);
  if(magic==='TSC1'){
    const count=b.length>=12?v.getUint16(4,true):0,period=b.length>=12?v.getInt32(8,true):0;
    if(count<1||count>128||b.length!==16+4*count||v.getUint16(6,true)!==0)throw Error('Invalid Scala scale record');
    const degrees=Array.from({length:count},(_,i)=>v.getInt32(12+4*i,true));
    validateTuning(degrees,period);return {kind:1,degrees,period};
  }
  if(magic==='TNP2'||magic==='TNP1'){
    let octaves,masks;
    if(magic==='TNP2'&&b.length===25){octaves=b[4];masks=Array.from({length:8},(_,i)=>v.getUint16(5+2*i,true));}
    else if(magic==='TNP1'&&b.length===12){masks=[v.getUint16(4,true),v.getUint16(6,true),0,0,0,0,0,0];
      if(masks[0]===0){masks[0]=masks[1];masks[1]=0;}octaves=masks[1]?2:1;}
    else throw Error('Invalid scale record');
    if(octaves<1||octaves>8||masks.some(m=>m>4095))throw Error('Invalid scale intervals');
    return {kind:1,octaves,masks};
  }
  if(magic!=='TUCP'||b.length<56)throw Error('Not an INTONO calibration or scale profile');
  const version=b[4],count=b[9],start=version>=4?48:36,limit=version===1?32:129;
  const name=String.fromCharCode(...b.subarray(12,12+b[8]));
  if(version<1||version>5||count<2||count>limit||b.length!==start+8*count+4||b[5]>3||b[6]>3||b[7]<12||b[7]>108||b[8]<1||b[8]>24||!name.trim()||/[^\x20-\x7e]/.test(name)||b.subarray(12+b[8],36).some(x=>x!==0)||b[10]>(version===1?0:3)|| (version<4&&b[11]!==0)||(version>=4&&b[11]>5))throw Error('Invalid calibration header');
  const zeroPitch=version===5?v.getInt32(44,true):null;
  if(version>=4&&(v.getUint32(36,true)>100000||v.getUint32(40,true)>100000)||version===4&&v.getInt32(44,true)!==0||version===5&&zeroPitch!==-2147483648&&(zeroPitch<0||zeroPitch>12800000))throw Error('Invalid calibration metadata');
  const points=Array.from({length:count},(_,i)=>({microvolts:v.getInt32(start+8*i,true),millicents:v.getInt32(start+8*i+4,true)}));
  if(points.some((p,i)=>p.microvolts<(version===1?0:-5000000)||p.microvolts>(version===1?2000000:version===2?5000000:8000000)||i>0&&(p.microvolts<=points[i-1].microvolts||p.millicents<=points[i-1].millicents)))throw Error('Calibration points must increase in voltage and pitch');
  return {kind:0,name,version,input:b[5],output:b[6],zeroNote:b[7],quality:b[11],points,raw:b};
}
export function encodeScale({octaves,masks}){
  if(!Number.isInteger(octaves)||octaves<1||octaves>8||masks.length!==8||masks.some(m=>!Number.isInteger(m)||m<0||m>4095))throw Error('Invalid scale intervals');
  const b=new Uint8Array(25),v=new DataView(b.buffer);b.set([84,78,80,50,octaves]);masks.forEach((m,i)=>v.setUint16(5+2*i,m,true));return finish(b);
}
function validateTuning(degrees,period){
  if(!Number.isInteger(period)||period<1||period>9600000||!Array.isArray(degrees)||degrees.length<1||degrees.length>128||degrees[0]!==0||degrees.some((d,i)=>!Number.isInteger(d)||d<0||d>=period||i>0&&d<=degrees[i-1]))throw Error('Tuning needs 1–128 ascending degrees, starting at zero, below a positive period of at most 9600 cents');
}
export function encodeTuning({degrees,period}){
  validateTuning(degrees,period);const b=new Uint8Array(16+4*degrees.length),v=new DataView(b.buffer);
  b.set([84,83,67,49]);v.setUint16(4,degrees.length,true);v.setInt32(8,period,true);
  degrees.forEach((d,i)=>v.setInt32(12+4*i,d,true));return finish(b);
}
export function renameCalibration(raw,name){
  if(name.length<1||name.length>24||!name.trim()||/[^\x20-\x7e]/.test(name))throw Error('Use 1–24 plain ASCII characters for the calibration name');
  if(decode(raw).kind!==0)throw Error('Not a calibration');
  const b=new Uint8Array(raw);b.fill(0,12,36);b[8]=name.length;b.set([...name].map(c=>c.charCodeAt(0)),12);return finish(b);
}
export function exportProfile(bytes,rawKind){const kind=rawKind===undefined?decode(bytes).kind:rawKind;return {format:'intono-profile',version:1,kind:['calibration','scale','config'][kind],record:Array.from(bytes)};}
export function importProfile(value){
  if(value.format!=='intono-profile'||value.version!==1||!Array.isArray(value.record)||value.record.length>1100||value.record.some(b=>!Number.isInteger(b)||b<0||b>255))throw Error('Invalid INTONO profile file');
  const bytes=Uint8Array.from(value.record),r=decode(bytes);
  if(value.kind!==['calibration','scale','config'][r.kind])throw Error('Profile type does not match its record');return bytes;
}
export function demoCalibration(){
  const b=new Uint8Array(52+25*8),v=new DataView(b.buffer);b.set([84,85,67,80,5,0,0,60,9,25,0,0]);b.set([... 'Demo VCO'].map(c=>c.charCodeAt(0)),12);
  // Header name length is eight characters.
  b[8]=8;v.setInt32(44,6000000,true);
  for(let i=0;i<25;i++){v.setInt32(48+8*i,i*100000,true);v.setInt32(52+8*i,6000000+i*120000,true);}return finish(b);
}

function validateName(name){if(typeof name!=='string'||name.length<1||name.length>24||!name.trim()||/[^\x20-\x7e]/.test(name))throw Error('Use 1–24 plain ASCII characters for the scale name');}
export function renameScale(raw,name){
  const r=decode(raw);if(r.kind!==1)throw Error('Not a scale');validateName(name);
  const inner=String.fromCharCode(...raw.subarray(0,4))==='TSN1'?raw.subarray(32,-4):raw;
  const b=new Uint8Array(inner.length+36);b.set([84,83,78,49,name.length]);b.set([...name].map(c=>c.charCodeAt(0)),8);b.set(inner,32);return finish(b);
}

// Stored route configs contain settings only; loading never starts outputs.
function decodeConfig(b){
  const magic=String.fromCharCode(...b.subarray(0,4)),lengths={TQS1:48,TQS2:56,TQS3:108,TQS4:116,TQS5:132,TQS6:136};
  if(b.length!==lengths[magic])throw Error('Invalid route config length');
  const v=new DataView(b.buffer,b.byteOffset,b.byteLength),width=magic==='TQS1'?10:magic==='TQS2'?12:25;
  const channels=Array.from({length:4},(_,i)=>{
    const at=4+i*width,x=b.subarray(at,at+width),transpose=x[4]>127?x[4]-256:x[4];
    const masks=width===25?Array.from({length:8},(_,n)=>v.getUint16(at+9+n*2,true)):[v.getUint16(at+6,true),v.getUint16(at+8,true),0,0,0,0,0,0];
    if(width!==25&&masks[0]===0){masks[0]=masks[1];masks[1]=0;}
    const scaleSlot=b.length>=132?b[124+i]:0,importedSlot=b.length===136?b[128+i]:0;
    const channel={input:x[0],zero:x[1],scale:x[2],root:x[3],transpose,equal:!!x[5],quantize:width===25?!!x[6]:width===10||!!x[10],correction:width===25?x[7]:width===12?x[11]:0,octaves:width===25?x[8]:masks[1]?2:1,masks,scaleSlot,importedSlot};
    if(channel.input>3||channel.zero<12||channel.zero>108||channel.scale>13||channel.root>11||Math.abs(transpose)>12||x[5]>1||(width===25&&x[6]>1)||(width===12&&x[10]>1)||channel.correction>9||channel.octaves<1||channel.octaves>8||masks.some(m=>m>4095)||scaleSlot>8||importedSlot>8||(importedSlot&&(channel.scale!==6||scaleSlot!==importedSlot)))throw Error('Invalid route output settings');
    return channel;
  });
  const inputs=b.length>=116?Array.from(b.subarray(104,108)):[0,1,2,3];
  const outputs=b.length>=116?Array.from(b.subarray(108,112)):[0,0,0,0];
  if(b.length<116)channels.forEach((c,i)=>outputs[c.input]|=1<<i);
  let usedOutputs=0,usedInputs=0;
  const routes=inputs.map((input,i)=>{
    const mask=outputs[i];if(input>3||mask>15||(mask&usedOutputs)||(mask&&(usedInputs&(1<<input))))throw Error('Route configs must assign each jack to only one route');
    usedOutputs|=mask;if(mask)usedInputs|=1<<input;
    const assigned=channels.filter((c,n)=>mask&(1<<n));if(assigned.some(c=>c.input!==input))throw Error('Route input does not match its outputs');
    const midi=b.length>=132?{channel:b[112+i*3],base:b[113+i*3],latch:!!b[114+i*3]}:{channel:0,base:60,latch:true};
    if(midi.channel>16||midi.base>127||(b.length>=132&&b[114+i*3]>1))throw Error('Invalid MIDI transpose settings');
    return {input,outputs:Array.from({length:4},(_,n)=>n).filter(n=>mask&(1<<n)),midi};
  });
  return {kind:2,channels,routes};
}
export function renameConfig(raw,name){
  const r=decode(raw);if(r.kind!==2)throw Error('Not a route config');validateName(name);
  const inner=String.fromCharCode(...raw.subarray(0,4))==='TCN1'?raw.subarray(32,-4):raw;
  const b=new Uint8Array(inner.length+36);b.set([84,67,78,49,name.length]);b.set([...name].map(c=>c.charCodeAt(0)),8);b.set(inner,32);return finish(b);
}
export function exportLibrary(banks){return {format:'intono-library',version:banks.length===3?2:1,banks:banks.map((bank,k)=>bank.map(b=>b?exportProfile(b,k):null))};}
export function importLibrary(value){
  if(value.format!=='intono-library'||![1,2].includes(value.version)||!Array.isArray(value.banks)||value.banks.length!==(value.version===1?2:3)||value.banks.some(b=>!Array.isArray(b)||b.length!==8))throw Error('Invalid INTONO library');
  return value.banks.map((bank,k)=>bank.map(p=>{if(p===null)return null;const bytes=importProfile(p);if(decode(bytes).kind!==k)throw Error('Profile is in the wrong bank');return bytes;}));
}
