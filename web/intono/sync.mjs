// Snapshot only changed, nonempty slots. Calibration and scales precede configs
// so a restored config's referenced profiles are written first.
export function changedSlots(banks,dirty){
  return banks.flatMap((bank,kind)=>bank.flatMap((bytes,index)=>
    bytes&&dirty[kind][index]?[{kind,slot:index+1,bytes:bytes.slice()}]:[]));
}

export async function writeChanges(device,queue,verified,progress){
  for(let i=0;i<queue.length;i++){
    const item=queue[i];progress(i,item);
    try{await device.write(item.kind,item.slot,item.bytes);}
    catch(e){throw Error(`Stopped at ${['Calibration','Scales','Configs'][item.kind]} slot ${item.slot}. ${i} of ${queue.length} slots verified. ${e.message}`);}
    verified(item);
  }
}
