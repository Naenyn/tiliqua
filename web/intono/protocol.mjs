// INTONO profile protocol v1. Fixed 32-byte frames, 16-byte stop-and-wait payloads.
// Requests: IP, op, seq, kind (0 CAL/1 scale/2 config), slot (1..8), offset LE16,
// count, reserved, total LE16, payload[16], reserved[3], CRC8/ATM.
// Replies: IR with echoed request identity, count, status, total, payload, CRC.
export const FRAME = 32, CHUNK = 16, MAX_RECORD = 1100;
export const OP = { hello:1, read:2, begin:3, write:4, commit:5, abort:6 };
export const STATUS = ['OK','Empty slot','Stop calibration, routes, and Reference CV before transferring profiles.',
  'Transfer expired or arrived out of order. Read the device again.',
  'The device rejected an invalid profile.', 'Flash operation failed. Read the slot to check its contents.'];
export function crc8(bytes) {
  let c=0; for(const b of bytes){c^=b;for(let i=0;i<8;i++)c=((c<<1)^((c&128)?7:0))&255;}return c;
}
export function packet(op, seq, kind=0, slot=1, offset=0, data=new Uint8Array(), total=0) {
  if(data.length>CHUNK || offset<0 || offset>65535 || total<0 || total>MAX_RECORD)throw Error('Invalid packet size');
  const p=new Uint8Array(FRAME),v=new DataView(p.buffer);
  p.set([73,80,op,seq,kind,slot]);v.setUint16(6,offset,true);p[8]=data.length;v.setUint16(10,total,true);
  p.set(data,12);p[31]=crc8(p.subarray(0,31));return p;
}
export class FrameReader {
  constructor(){this.bytes=[];}
  push(chunk){
    const result=[];
    for(const byte of chunk){
      this.bytes.push(byte);
      if(this.bytes.length<FRAME)continue;
      if(this.bytes[0]!==73||this.bytes[1]!==82){this.bytes.shift();continue;}
      const p=Uint8Array.from(this.bytes);
      if(p[31]!==crc8(p.subarray(0,31))||p[8]>CHUNK){this.bytes.shift();continue;}
      this.bytes=[];result.push(p);
    }
    // At most one incomplete frame is retained, regardless of diagnostic noise.
    return result;
  }
}
export class Device {
  constructor(port,onDisconnect=()=>{}){this.port=port;this.onDisconnect=onDisconnect;this.seq=Math.floor(Math.random()*256);this.parser=new FrameReader();this.pending=null;this.closed=false;}
  async open(){
    await this.port.open({baudRate:115200});
    if(this.port.setSignals)await this.port.setSignals({dataTerminalReady:true,requestToSend:false});
    this.reader=this.port.readable.getReader();this.writer=this.port.writable.getWriter();
    this.pumpTask=this.pump();
    const h=await this.request(OP.hello);
    if(h[12]!==1||h[13]!==8||h[14]!==CHUNK)throw Error('Unsupported INTONO profile protocol');
    this.scalaSupported=h[8]>=5 && !!(h[16]&1);this.namesSupported=h[8]>=5 && !!(h[16]&2);this.configsSupported=h[8]>=5 && !!(h[16]&4);
  }
  async pump(){
    let error=Error('Device disconnected');
    try{while(!this.closed){const {value,done}=await this.reader.read();if(done)break;
      for(const p of this.parser.push(value)){
        const q=this.pending;
        if(q&&p[2]===q.packet[2]&&p[3]===q.packet[3]&&p[4]===q.packet[4]&&p[5]===q.packet[5]&&p[6]===q.packet[6]&&p[7]===q.packet[7]){
          this.pending=null;clearTimeout(q.timer);q.resolve(p);
        }
      }
    }}catch(e){error=e;}finally{
      const unexpected=!this.closed;this.closed=true;this.fail(error);
      if(unexpected)this.onDisconnect(error);
    }
  }
  fail(error){if(this.pending){clearTimeout(this.pending.timer);this.pending.reject(error);this.pending=null;}}
  async request(op,kind=0,slot=1,offset=0,data=new Uint8Array(),total=0){
    if(this.closed)throw Error('Device disconnected. Reconnect before transferring profiles.');
    if(this.pending)throw Error('A transfer is already in progress');
    const p=packet(op,this.seq=(this.seq+1)&255,kind,slot,offset,data,total);
    const reply=new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{this.pending=null;reject(Error(op===OP.commit?
        'Write acknowledgement was lost. Read this slot before retrying; it may have been saved.':
        'No reply from INTONO. Launch the profile utility firmware and reconnect.'));},8000);
      this.pending={packet:p,resolve,reject,timer};
    });
    let r;
    try{[,r]=await Promise.all([this.writer.write(p),reply]);}catch(e){this.fail(e);throw e;}
    if(r[9]!==0 && !(op===OP.read&&r[9]===1))throw Error(STATUS[r[9]]||'Unknown device error');
    return r;
  }
  async read(kind,slot){
    if(kind===2&&!this.configsSupported)throw Error("Update INTONO firmware before transferring route configs.");
    let r=await this.request(OP.read,kind,slot);if(r[9]===1)return null;
    const n=new DataView(r.buffer).getUint16(10,true);
    if(n<1||n>MAX_RECORD)throw Error('Invalid device record length');
    const bytes=new Uint8Array(n);
    for(let offset=0;offset<n;offset+=CHUNK){
      if(offset)r=await this.request(OP.read,kind,slot,offset);
      if(r[9]!==0||new DataView(r.buffer).getUint16(10,true)!==n||r[8]!==Math.min(CHUNK,n-offset))throw Error('Incomplete device record');
      bytes.set(r.subarray(12,12+r[8]),offset);
    }return bytes;
  }
  validateWrite(kind,bytes){
    if(kind===2&&!this.configsSupported)throw Error("Update INTONO firmware before transferring route configs.");
    if(kind===1 && new TextDecoder().decode(bytes.subarray(0,4))==='TSN1' && !this.namesSupported)throw Error('Update INTONO firmware before writing named scales.');
    const tuning=kind===1 && new TextDecoder().decode(bytes.subarray(0,4))==='TSN1'?bytes.subarray(32,-4):bytes;
    if(kind===1 && tuning[0]===84 && tuning[1]===83 && tuning[2]===67 && tuning[3]===49 && !this.scalaSupported)throw Error("Update INTONO firmware before writing a microtonal Scala tuning.");
  }
  async write(kind,slot,bytes){
    this.validateWrite(kind,bytes);
    await this.request(OP.begin,kind,slot,0,new Uint8Array(),bytes.length);
    for(let offset=0;offset<bytes.length;offset+=CHUNK)await this.request(OP.write,kind,slot,offset,bytes.subarray(offset,offset+CHUNK));
    await this.request(OP.commit,kind,slot);
    const check=await this.read(kind,slot);
    if(!check||check.length!==bytes.length||check.some((b,i)=>b!==bytes[i]))throw Error('Read-back verification failed');
  }
  close(){
    // USB disconnect, reader failure, and the Disconnect button can race.
    if(!this.closeTask)this.closeTask=this.release();
    return this.closeTask;
  }
  async release(){
    this.closed=true;this.fail(Error('Connection closed'));
    if(this.reader){await this.reader.cancel().catch(()=>{});await this.pumpTask;this.reader.releaseLock();}
    if(this.writer)this.writer.releaseLock();await this.port.close().catch(()=>{});
  }
}
