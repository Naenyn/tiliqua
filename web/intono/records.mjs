// Saved scales contain intervals, never a root key. Calibration units are
// signed microvolts and millicents, matching the firmware's versioned codecs.
export function crc32(bytes){let c=0xffffffff;for(const b of bytes){c^=b;for(let i=0;i<8;i++)c=(c>>>1)^((c&1)?0xedb88320:0);}return (~c)>>>0;}
function finish(b){new DataView(b.buffer,b.byteOffset,b.byteLength).setUint32(b.length-4,crc32(b.subarray(0,-4)),true);return b;}
export function decode(bytes){
  const b=new Uint8Array(bytes),v=new DataView(b.buffer),magic=String.fromCharCode(...b.subarray(0,4));
  if(b.length<8||v.getUint32(b.length-4,true)!==crc32(b.subarray(0,-4)))throw Error('Profile checksum does not match');
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
export function renameCalibration(raw,name){
  if(name.length<1||name.length>24||!name.trim()||/[^\x20-\x7e]/.test(name))throw Error('Use 1–24 plain ASCII characters for the calibration name');
  if(decode(raw).kind!==0)throw Error('Not a calibration');
  const b=new Uint8Array(raw);b.fill(0,12,36);b[8]=name.length;b.set([...name].map(c=>c.charCodeAt(0)),12);return finish(b);
}
export function exportProfile(bytes){const r=decode(bytes);return {format:'intono-profile',version:1,kind:r.kind===0?'calibration':'scale',record:Array.from(bytes)};}
export function importProfile(value){
  if(value.format!=='intono-profile'||value.version!==1||!Array.isArray(value.record)||value.record.length>1100||value.record.some(b=>!Number.isInteger(b)||b<0||b>255))throw Error('Invalid INTONO profile file');
  const bytes=Uint8Array.from(value.record),r=decode(bytes);
  if(value.kind!==(r.kind===0?'calibration':'scale'))throw Error('Profile type does not match its record');return bytes;
}
export function demoCalibration(){
  const b=new Uint8Array(52+25*8),v=new DataView(b.buffer);b.set([84,85,67,80,5,0,0,60,9,25,0,0]);b.set([... 'Demo VCO'].map(c=>c.charCodeAt(0)),12);
  // Header name length is eight characters.
  b[8]=8;v.setInt32(44,6000000,true);
  for(let i=0;i<25;i++){v.setInt32(48+8*i,i*100000,true);v.setInt32(52+8*i,6000000+i*120000,true);}return finish(b);
}
