import {test} from 'node:test';
import assert from 'node:assert/strict';
import {packet,crc8,FrameReader,Device,OP,MAX_RECORD} from './protocol.mjs';
import {crc32,decode,encodeTuning,encodeScale,renameConfig,exportLibrary,importLibrary,renameScale,renameCalibration,exportProfile,importProfile,demoCalibration} from './records.mjs';
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
    else if(op===1){const caps=this.capabilities||[1,8,16,8];r[8]=caps.length;r.set(caps,12);}
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

import {importScala,exportScala,MAX_SCALA_BYTES} from './scala.mjs';
test('Scala imports cents, integer ratios, comments, labels, CRLF, and empty descriptions',()=>{
  const major='! major.scl\r\n\r\n7\r\n  ! pitches\r\n200.0 D\r\n400. E\r\n500.0\r\n700.0\r\n900.0\r\n1100.0\r\n2/1 octave\r\n';
  const r=importScala(major);assert.equal(r.description,'');assert.equal(decode(r.bytes).masks[0],0xab5);
  assert.equal(decode(importScala('Two octaves\n2\n2\n4 / 1\n').bytes).octaves,2);
  assert.equal(decode(importScala('Period only\n1\n2\n').bytes).masks[0],1);
});
test('Scala preserves microtonal pitches and non-octave periods',()=>{
  const just=decode(importScala('Just\n3\n5/4\n3/2\n2/1').bytes);
  assert.deepEqual(just,{kind:1,degrees:[0,386314,701955],period:1200000});
  assert.deepEqual(decode(importScala('24 EDO\n2\n50.0\n1200.0').bytes),{kind:1,degrees:[0,50000],period:1200000});
  assert.deepEqual(decode(importScala('Bohlen Pierce\n1\n3/1').bytes),{kind:1,degrees:[0],period:1901955});
  assert.deepEqual(decode(importScala('Precision\n2\n12.3456\n100.0').bytes),{kind:1,degrees:[0,12346],period:100000});
  for(const source of ['Bad\n0','Bad\n129','Bad\n2\n100.0','Bad\n1\n1/0','Bad\n1\n-5.0','Bad\n1\n0.0','Bad\n1\n100oops','Bad\n2\n200.0\n100.0','Bad\n2\n100.0\n100.0','Bad\n2\n100.0001\n100.0002','Bad\n1\n10800.0'])assert.throws(()=>importScala(source));
});
test('generic tuning records round-trip, validate bounds, and reject corruption',()=>{
  const bytes=encodeTuning({degrees:Array.from({length:128},(_,i)=>i*73125),period:9600000});
  assert.deepEqual(importScala(exportScala(bytes)).bytes,bytes);
  assert.deepEqual(importProfile(exportProfile(bytes)),bytes);
  for(let i=0;i<bytes.length;i++){const bad=bytes.slice();bad[i]^=1;assert.throws(()=>decode(bad));}
  for(const tuning of [{degrees:[],period:1200000},{degrees:[1],period:1200000},{degrees:[0,0],period:1200000},{degrees:[0,1200000],period:1200000},{degrees:[0,1.1],period:1200000},{degrees:[0],period:9600001}])assert.throws(()=>encodeTuning(tuning));
});
test('Scala export round-trips every unison-containing keyboard mask and multi-octave patterns',()=>{
  for(let mask=1;mask<=4095;mask+=2){const bytes=encodeScale({octaves:1,masks:[mask,0,0,0,0,0,0,0]});assert.deepEqual(importScala(exportScala(bytes)).bytes,bytes);}
  const bytes=encodeScale({octaves:8,masks:[1,2,4,8,16,32,64,128]});assert.deepEqual(importScala(exportScala(bytes)).bytes,bytes);
  assert.throws(()=>exportScala(encodeScale({octaves:1,masks:[2,0,0,0,0,0,0,0]})),/omits interval 0/);
  assert.throws(()=>exportScala(demoCalibration()),/Choose a scale/);
});

test('older firmware cannot receive Scala records accidentally',async()=>{
  const port=new MockPort(),dev=new Device(port);await dev.open();assert.equal(dev.scalaSupported,false);
  const tuning=encodeTuning({degrees:[0,386314],period:1200000});
  await assert.rejects(dev.write(1,1,tuning),/Update INTONO firmware/);assert.equal(port.writes,0);
  dev.scalaSupported=true;await dev.write(1,1,tuning);assert.deepEqual(await dev.read(1,1),tuning);await dev.close();
});

// The native picker filter must agree with the formats accepted by each action.
import {readFileSync} from 'node:fs';
test('profile picker permits Scala while library picker remains JSON-only',()=>{
  const html=readFileSync(new URL('./index.html',import.meta.url),'utf8');
  const accept=id=>html.match(new RegExp(`id="${id}"[^>]*accept="([^\"]+)"`))[1].split(',');
  assert.ok(accept('importProfile').includes('.scl'));
  assert.ok(accept('importProfile').includes('.json'));
  assert.ok(!accept('importLibrary').includes('.scl'));
});
test('five out of nineteen equal temperament Scala file preserves its intervals',()=>{
  const source='! 05-19.scl\r\n!\r\n5 out of 19-tET\r\n 5\r\n!\r\n 252.63158\r\n 505.26316\r\n 757.89474\r\n 1010.52632\r\n 2/1\r\n';
  assert.deepEqual(decode(importScala(source).bytes),{kind:1,degrees:[0,252632,505263,757895,1010526],period:1200000});
});

test('Scala byte limit accepts the boundary and rejects oversize UTF-8 and interval counts',()=>{
  const valid='Boundary\n1\n2/1\n';
  const atLimit=valid+'!'+ 'x'.repeat(MAX_SCALA_BYTES-valid.length-1);
  assert.equal(new TextEncoder().encode(atLimit).length,MAX_SCALA_BYTES);
  assert.equal(decode(importScala(atLimit).bytes).octaves,1);
  assert.throws(()=>importScala(atLimit+'x'),/100,000-byte limit/);
  const unicode='é'.repeat(50000)+'\n1\n2/1';
  assert.ok(unicode.length<MAX_SCALA_BYTES);
  assert.throws(()=>importScala(unicode),/100,000-byte limit/);
  assert.throws(()=>importScala('Too many\n129\n'+Array(129).fill('1.0').join('\n')),/1–128 pitches/);
});

test('named keyboard and maximum Scala scales preserve intervals and reject corruption',()=>{
  const records=[encodeScale({octaves:8,masks:[1,2,4,8,16,32,64,128]}),encodeTuning({period:1200000,degrees:Array.from({length:128},(_,i)=>i*9000)})];
  for(const raw of records){
    const named=renameScale(raw,'123456789012345678901234');
    assert.deepEqual(decode(named),{...decode(raw),name:'123456789012345678901234'});
    assert.deepEqual(named.subarray(32,-4),raw);
    const renamed=renameScale(named,'My tuning');assert.equal(renamed.length,named.length);
    assert.deepEqual(renamed.subarray(32,-4),raw);
    assert.deepEqual(importProfile(exportProfile(renamed)),renamed);
    for(let i=0;i<named.length;i++){const bad=named.slice();bad[i]^=1;assert.throws(()=>decode(bad));}
    for(const name of ['', ' ', 'x'.repeat(25),'🎹','a\n'])assert.throws(()=>renameScale(raw,name));
  }
  assert.equal(renameScale(records[1],'Max table').length,564);
  assert.throws(()=>renameScale(demoCalibration(),'Not a scale'));
});
test('old firmware rejects named scales before sending a write',async()=>{
  const p=new MockPort(),d=new Device(p);await d.open();
  const named=renameScale(encodeScale({octaves:1,masks:[4095,0,0,0,0,0,0,0]}),'Chromatic');
  await assert.rejects(d.write(1,1,named),/named scales/);assert.equal(p.writes,0);
  d.namesSupported=true;await d.write(1,1,named);assert.deepEqual(await d.read(1,1),named);
  await d.close();
});

test('new firmware advertises names and Scala independently',async()=>{
  for(const capability of [1,2,3]){
    const p=new MockPort();p.capabilities=[1,8,16,8,capability];const d=new Device(p);await d.open();
    assert.equal(d.scalaSupported,!!(capability&1));assert.equal(d.namesSupported,!!(capability&2));
    const tuning=renameScale(encodeTuning({degrees:[0,386314,701955],period:1200000}),'Named tuning');
    if(capability===3){await d.write(1,1,tuning);assert.deepEqual(await d.read(1,1),tuning);}
    else {await assert.rejects(d.write(1,1,tuning),/Update INTONO/);assert.equal(p.writes,0);}
    await d.close();
  }
});

function configFixture(){
  const b=new Uint8Array(136),v=new DataView(b.buffer);b.set([84,81,83,54]);
  for(let n=0;n<4;n++){const at=4+n*25;b.set([n,60,0,0,0,0,1,0,1],at);v.setUint16(at+9,4095,true);b[104+n]=n;b[108+n]=1<<n;b.set([0,60,1],112+n*3);}
  v.setUint32(132,crc32(b.subarray(0,132)),true);return b;
}
test('config names preserve route settings; library backups include three banks',()=>{
  const raw=configFixture(),named=renameConfig(raw,'Four voices'),r=decode(named);
  assert.equal(r.kind,2);assert.equal(r.name,'Four voices');assert.deepEqual(named.subarray(32,-4),raw);
  assert.deepEqual(r.routes[0],{input:0,outputs:[0],midi:{channel:0,base:60,latch:true}});
  assert.deepEqual(decode(renameConfig(named,'New name')),{...r,name:'New name'});
  const banks=Array.from({length:3},()=>Array(8).fill(null));banks[0][0]=demoCalibration();banks[1][7]=encodeTuning({degrees:[0,50000],period:1200000});banks[2][3]=named;
  const library=exportLibrary(banks);assert.equal(library.version,2);assert.deepEqual(importLibrary(library),banks);
  assert.deepEqual(importProfile(exportProfile(named)),named);
  assert.deepEqual(importLibrary(exportLibrary(banks.slice(0,2))),banks.slice(0,2));
  for(let n=0;n<named.length;n++){const bad=named.slice();bad[n]^=1;assert.throws(()=>decode(bad));}
});
test('config fields and conflicting assignments are rejected even with valid checksums',()=>{
  for(const [offset,value] of [[4,4],[5,0],[7,12],[9,2],[10,2],[11,10],[12,9],[104,4],[108,16],[109,1],[112,17],[113,128],[114,2],[124,9],[128,9],[105,0]]){
    const b=configFixture();b[offset]=value;new DataView(b.buffer).setUint32(132,crc32(b.subarray(0,132)),true);assert.throws(()=>decode(b),`invalid ${offset}`);
  }
  assert.throws(()=>renameConfig(encodeScale({octaves:1,masks:[1,0,0,0,0,0,0,0]}),'Wrong type'));
});
test('config transfer is capability gated and read back after writing',async()=>{
  const p=new MockPort(),d=new Device(p);await d.open();const record=renameConfig(configFixture(),'Transfer');
  await assert.rejects(d.read(2,1),/route configs/);await assert.rejects(d.write(2,1,record),/route configs/);assert.equal(p.writes,0);await d.close();
  const modern=new MockPort();modern.capabilities=[1,8,16,8,7];const device=new Device(modern);await device.open();assert.equal(device.configsSupported,true);
  await device.write(2,8,record);assert.deepEqual(await device.read(2,8),record);await device.close();
});

test('bulk write snapshots changed nonempty slots across banks in dependency order',async()=>{
  const {changedSlots,writeChanges}=await import('./sync.mjs');
  const banks=[[new Uint8Array([1]),null,new Uint8Array([3])],[new Uint8Array([4])],[new Uint8Array([5])]];
  const dirty=[[true,true,false],[true],[true]],queue=changedSlots(banks,dirty);
  assert.deepEqual(queue.map(({kind,slot})=>[kind,slot]),[[0,1],[1,1],[2,1]]);
  banks[0][0][0]=99;assert.equal(queue[0].bytes[0],1);
  const writes=[],progress=[];
  await writeChanges({write:async(k,s,b)=>{writes.push([k,s,b[0]]);}},queue,item=>{dirty[item.kind][item.slot-1]=false;},n=>progress.push(n));
  assert.deepEqual(writes,[[0,1,1],[1,1,4],[2,1,5]]);assert.deepEqual(progress,[0,1,2]);
  assert.deepEqual(changedSlots(banks,dirty),[]);assert.equal(dirty[0][1],true);
});
test('failed bulk write stops and leaves failed and unattempted slots for retry',async()=>{
  const {changedSlots,writeChanges}=await import('./sync.mjs');
  const banks=[[new Uint8Array([1])],[new Uint8Array([2])],[new Uint8Array([3])]],dirty=[[true],[true],[true]],calls=[];
  await assert.rejects(()=>writeChanges({write:async(k,s)=>{calls.push(k);if(k===1)throw Error('Read-back verification failed');}},changedSlots(banks,dirty),item=>{dirty[item.kind][item.slot-1]=false;},()=>{}),/Scales slot 1.*1 of 3 slots verified.*Read-back verification failed/);
  assert.deepEqual(calls,[0,1]);assert.deepEqual(changedSlots(banks,dirty).map(i=>i.kind),[1,2]);
});

test('serial EOF and reader failure close the connection and reject further requests',async()=>{
  for(const failure of [false,true]){
    const port=new MockPort();let notifications=0,closes=0;
    port.close=async()=>{closes++;};
    const device=new Device(port,()=>{notifications++;});await device.open();
    if(failure)port.controller.error(Error('USB read failed'));else port.controller.close();
    await device.pumpTask;
    assert.equal(device.closed,true);assert.equal(notifications,1);
    await assert.rejects(device.read(0,1),/disconnected/);
    await Promise.all([device.close(),device.close()]);assert.equal(closes,1);
    assert.equal(port.readable.locked,false);assert.equal(port.writable.locked,false);
  }
});
test('manual disconnect does not report an unexpected connection loss',async()=>{
  const port=new MockPort();let notifications=0;
  const device=new Device(port,()=>{notifications++;});await device.open();await device.close();
  assert.equal(notifications,0);assert.equal(device.closed,true);
});
