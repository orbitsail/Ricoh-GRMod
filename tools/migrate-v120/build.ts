// SPDX-License-Identifier: GPL-2.0-only
/** Build locally from pinned private inputs; no device access. Usage: vite-node tools/migrate-v120/build.ts INVENTORY.json OFFICIAL111 OFFICIAL120 OUT */
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {Engine,fw} from '../../core/src';
const [inventory,file111,file120,out]=process.argv.slice(2);
if(!out) throw Error('usage: INVENTORY.json OFFICIAL111 OFFICIAL120 OUT');
mkdirSync(out,{recursive:true});
const inv=JSON.parse(readFileSync(inventory,'utf8'));
const hash=(b:Uint8Array)=>createHash('sha256').update(b).digest('hex');
const report:any[]=[];
for(const [version,path,pinned] of [['111',file111,''],['120',file120,'7563d7e462f0c53b6ab2fbab7cdfbbb57151a41192ee82f4f3a2108f9d77650d']]){
 const raw=new Uint8Array(readFileSync(path));
 if(version==='120'&&hash(raw)!==pinned)throw Error('official hash mismatch');
 const eng=await Engine.open(raw);
 const options:any={...inv.features,extraSlots:inv.extras.map((x:any)=>({...x,icon:new Uint8Array(x.icon)}))};
 if(version==='120')options.lookLayout.order=[...inv.features.lookLayout.order.filter((x:number)=>x<34),31,32,...inv.features.lookLayout.order.filter((x:number)=>x>=34).map((x:number)=>x+4)];
 for(const variant of ['off','fit','awb','final']){
  const flags=variant==='off'?{}:{brightAuto:'balanced',awbFit:true,...(variant==='awb'||variant==='final'?{awbLearn:true}:{}),...(variant==='final'?{shadowLearn:true}:{})};
  const b=await eng.buildFirmware([],inv.ratios,[],{...options,...flags});
  if(!Object.values(b.checks).every(x=>x===true))throw Error('build check failed');
  const d=new fw.Firmware(b.file).decoded,ss=fw.sectionsOf(d),r=ss.find(x=>x.name==='RTOS')!,i=ss.find(x=>x.name==='ICONBIN')!;
  const rt=d.slice(r.offset,r.offset+r.size);
  writeFileSync(`${out}/${version}-${variant}.bin`,b.file);writeFileSync(`${out}/${version}-${variant}.rtos`,rt);
  writeFileSync(`${out}/${version}-${variant}.icons`,d.subarray(i.offset,i.offset+i.size));
  const summary=await eng.inspect(b.file);
  if(!summary.verified)throw Error('full inspect reconstruction failed: '+version+'-'+variant);
  if(variant==='off'&&!Buffer.from(b.file).equals(readFileSync(`${out}/upstream-off-${version}.bin`)))throw Error('disabled build differs from upstream '+version);
  report.push({version,variant,sha256:b.sha256,rtosSha256:hash(rt),bytes:b.file.length,checks:b.checks,inspectVerified:summary.verified,features:summary,flags});
  console.log(version,variant,b.sha256,'inspect verified');
  if(variant==='final'){
   if(version==='120')writeFileSync(out+'/fwdc248b.bin',b.file);
   // Historical-behaviour controls, same final module/hook, only ctx settings differ.
   const hook=version==='120'?0x53960e90:0x53938e2c;
   const dv=new DataView(rt.buffer,rt.byteOffset,rt.byteLength);const w=dv.getUint32(hook-0x53000000,true);const rel=(w<<8)>>8;const stub=hook+8+rel*4;
   const imm=(a:number)=>{const x=dv.getUint32(a-0x53000000,true);return ((x>>>4)&0xf000)|(x&0xfff)};
   const ctx=imm(stub+12)|(imm(stub+16)<<16);
   const prev=rt.slice();new DataView(prev.buffer).setUint32(ctx-0x53000000+18*4,1,true);new DataView(prev.buffer).setUint32(ctx-0x53000000+19*4,0,true);
   writeFileSync(`${out}/${version}-legacy-unscaled.rtos`,prev);
   const prevScaled=rt.slice();new DataView(prevScaled.buffer).setUint32(ctx-0x53000000+18*4,1,true);writeFileSync(`${out}/${version}-legacy-missingexp.rtos`,prevScaled);
  }
 }
}
writeFileSync(out+'/build-report.json',JSON.stringify(report,(_:string,v:any)=>ArrayBuffer.isView(v)?Array.from(v as unknown as ArrayLike<number>):v,2));
