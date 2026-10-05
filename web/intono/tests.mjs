import {test} from 'node:test';
import assert from 'node:assert/strict';
import {packet,crc8,FrameReader,Device,OP,MAX_RECORD} from './protocol.mjs';
import {crc32,decode,encodeScale,renameCalibration,exportProfile,importProfile,demoCalibration} from './records.mjs';
test('CRC reference vectors',()=>{const b=new TextEncoder().encode('123456789');assert.equal(crc8(b),0xf4);assert.equal(crc32(b),0xcbf43926);});
test('all intervals, octave bounds, and legacy scale import',()=>{
  for(let mask=0;mask<4096;mask++){const masks=[mask,4095^mask,0,1,2,3,4,5];assert.deepEqual(decode(encodeScale({octaves:8,masks})),{kind:1,octaves:8,masks});}
  assert.throws(()=>encodeScale({octaves:9,masks:Array(8).fill(0)}));
  const b=new Uint8Array([84,78,80,49,0,0,1,0,0,0,0,0]);new DataView(b.buffer).setUint32(8,crc32(b.subarray(0,8)),true);
  assert.deepEqual(decode(b),{kind:1,octaves:1,masks:[1,0,0,0,0,0,0,0]});
});
test('calibration rename preserves measurements and corrupt files are rejected',()=>{
  const b=demoCalibration(),r=decode(b);assert.equal(r.name,'Demo VCO');
  const changed=renameCalibration(b,'Waveplane');assert.equal(decode(changed).name,'Waveplane');assert.deepEqual(decode(changed).points,r.points);
  assert.deepEqual(changed.subarray(36,-4),b.subarray(36,-4));assert.throws(()=>renameCalibration(b,'🎹'));
  assert.deepEqual(importProfile(exportProfile(b)),b);
  for(let i=0;i<b.length;i++){const bad=b.slice();bad[i]^=1;assert.throws(()=>decode(bad));}
  const bad=exportProfile(b);bad.record[1]=256;assert.throws(()=>importProfile(bad));
});
test('response parser survives diagnostics, corruption, noise, and arbitrary fragmentation',()=>{
  const r=packet(OP.hello,7);r[1]=82;r[31]=crc8(r.subarray(0,31));const bad=r.slice();bad[12]^=1;
  const stream=new Uint8Array([...new TextEncoder().encode('VIDEO health\n'),...bad,23,...r,...r]);
  for(let chunk=1;chunk<65;chunk++){const parser=new FrameReader(),frames=[];for(let offset=0;offset<stream.length;offset+=chunk)frames.push(...parser.push(stream.subarray(offset,offset+chunk)));assert.equal(frames.length,2);assert.deepEqual(frames[0],r);assert.ok(parser.bytes.length<32);}
});
class MockPort {
  constructor(){this.records=new Map();this.writes=0;this.upload=null;this.failCommit=false;this.busy=false;
    this.readable=new ReadableStream({start:c=>{this.controller=c;}});
    this.writable=new WritableStream({write:p=>this.reply(p)});}
  async open(){} async close(){}
  reply(p){
    const r=new Uint8Array(32),view=new DataView(r.buffer);r.set([73,82]);r.set(p.subarray(2,8),2);
    const op=p[2],key=`${p[4]}:${p[5]}`,offset=p[6]|p[7]<<8;
    if(this.busy&&op!==1)r[9]=2;
    else if(op===1){r[8]=4;r.set([1,8,16,8],12);}
    else if(op===2){const b=this.records.get(key);if(!b)r[9]=1;else{view.setUint16(10,b.length,true);r[8]=Math.min(16,b.length-offset);r.set(b.subarray(offset,offset+16),12);}}
    else if(op===3)this.upload={key,bytes:new Uint8Array(p[10]|p[11]<<8)};
    else if(op===4)this.upload.bytes.set(p.subarray(12,12+p[8]),offset);
    else if(op===5){this.records.set(key,this.upload.bytes);this.writes++;if(this.failCommit){r[9]=5;}}
    r[31]=crc8(r.subarray(0,31));this.controller.enqueue(new TextEncoder().encode('CAL status\n'));this.controller.enqueue(r.subarray(0,9));this.controller.enqueue(r.subarray(9));
  }
}
test('full-size device exchange reads, writes, verifies, and never writes on read',async()=>{
  const port=new MockPort(),dev=new Device(port);await dev.open();assert.equal(await dev.read(0,1),null);assert.equal(port.writes,0);
  const b=Uint8Array.from({length:MAX_RECORD},(_,i)=>i&255);await dev.write(0,8,b);assert.deepEqual(await dev.read(0,8),b);assert.equal(port.writes,1);await dev.close();
});
test('busy and failed commit are surfaced with no automatic write retry',async()=>{
  const port=new MockPort(),dev=new Device(port);await dev.open();port.busy=true;await assert.rejects(dev.read(0,1),/Stop calibration/);assert.equal(port.writes,0);
  port.busy=false;port.failCommit=true;await assert.rejects(dev.write(1,1,new Uint8Array(25)),/Flash operation failed/);assert.equal(port.writes,1);await dev.close();
});
