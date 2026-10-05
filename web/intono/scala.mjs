import {decode,encodeScale,encodeTuning} from './records.mjs';

export const MAX_SCALA_BYTES=100000;

// Scala's final pitch is the repeating period; unison is implicit.
// Preserve microtonal intervals at the firmware's 0.001-cent precision.
export function importScala(text){
  if(typeof text!=='string')throw Error('Scala input must be text');
  if(text.length>MAX_SCALA_BYTES||new TextEncoder().encode(text).length>MAX_SCALA_BYTES)throw Error('Scala file exceeds the 100,000-byte limit');
  const lines=text.replace(/^\uFEFF/,'').split(/\r\n?|\n/).filter(line=>!line.trimStart().startsWith('!'));
  if(lines.length<2)throw Error('Scala file needs a description and pitch count');
  const description=lines.shift().trim(),countLine=lines.shift().trim();
  if(!/^\d+$/.test(countLine))throw Error('Invalid Scala pitch count');
  const count=Number(countLine);
  if(count<1||count>128)throw Error('Scala files must contain 1–128 pitches, including the repeating period');
  if(lines.length<count)throw Error(`Scala file declares ${count} pitches but contains fewer pitch lines`);
  const pitches=lines.slice(0,count).map((line,i)=>{
    const match=line.trim().match(/^([+-]?(?:\d+\.\d*|\.\d+)|\d+\s*\/\s*\d+|\d+)(?=\s|$)/);
    if(!match)throw Error(`Invalid Scala pitch on degree ${i+1}`);
    const token=match[1];let cents;
    if(token.includes('.'))cents=Number(token);
    else {const [a,b='1']=token.split('/').map(s=>s.trim());const numerator=Number(a),denominator=Number(b);
      if(!Number.isSafeInteger(numerator)||!Number.isSafeInteger(denominator)||numerator<=0||denominator<=0)throw Error(`Invalid ratio on degree ${i+1}`);
      cents=1200*Math.log2(numerator/denominator);
    }
    if(!Number.isFinite(cents)||cents<=0)throw Error('INTONO needs positive, ascending Scala pitches');
    const millicents=Math.round(cents*1000);
    if(!Number.isSafeInteger(millicents)||millicents<1||millicents>9600000)throw Error('Scala pitches must be between 0.001 and 9600 cents');
    return millicents;
  });
  if(pitches.some((pitch,i)=>i>0&&pitch<=pitches[i-1]))throw Error('INTONO needs strictly ascending Scala pitches');
  const period=pitches.at(-1);
  if(period%1200000===0&&pitches.every(p=>p%100000===0)){
    const masks=Array(8).fill(0);masks[0]=1;
    for(const pitch of pitches.slice(0,-1)){const semitone=pitch/100000;masks[Math.floor(semitone/12)]|=1<<(semitone%12);}
    return {description,bytes:encodeScale({octaves:period/1200000,masks})};
  }
  return {description,bytes:encodeTuning({degrees:[0,...pitches.slice(0,-1)],period})};
}

export function exportScala(bytes){
  const scale=decode(bytes);if(scale.kind!==1)throw Error('Choose a scale to export as Scala');
  if(scale.degrees){const pitches=[...scale.degrees.slice(1),scale.period].map(p=>(p/1000).toFixed(3));return ['! Exported by INTONO Profile Library','INTONO interval tuning',String(pitches.length),'!',...pitches,''].join('\n');}
  if(!(scale.masks[0]&1))throw Error('Scala always includes unison. This scale omits interval 0, so exporting it would change the scale.');
  const pitches=[];
  for(let octave=0;octave<scale.octaves;octave++)for(let note=0;note<12;note++)if((octave||note)&&(scale.masks[octave]&(1<<note)))pitches.push(`${(octave*12+note)*100}.0`);
  pitches.push(`${scale.octaves*1200}.0`);
  return ['! Exported by INTONO Profile Library','INTONO interval scale',String(pitches.length),'!',...pitches,''].join('\n');
}
