// SPDX-License-Identifier: GPL-2.0-only
import {readFileSync,writeFileSync,readdirSync} from 'node:fs';
import {Engine,fw} from '../../core/src';
const [inventory,official,candidate,lutDir,out]=process.argv.slice(2);
const inv=JSON.parse(readFileSync(inventory,'utf8'));
const raw=new Uint8Array(readFileSync(candidate)),d=new fw.Firmware(raw).decoded,ss=fw.sectionsOf(d),r=ss.find(x=>x.name==='RTOS')!,i=ss.find(x=>x.name==='ICONBIN')!;
const mod=await import('../../core/src/fw/gr4v120/aspect/slots');
const extras=mod.readExtraSlots(d.subarray(r.offset,r.offset+r.size),d.subarray(i.offset,i.offset+i.size),20)!;
const norm=(x:any)=>JSON.stringify(x,(_:string,v:any)=>ArrayBuffer.isView(v)?Array.from(v as unknown as ArrayLike<number>):v);
const preserved=extras.map((e,k)=>({index:k+1,name:e.name,style:38+k,colorAndIconExact:norm(e)===norm(inv.extras[k])}));
if(!preserved.every(x=>x.colorAndIconExact))throw Error('slot migration mismatch');
const eng=await Engine.open(new Uint8Array(readFileSync(official)));
const imports=[];
for(const name of readdirSync(lutDir).filter(x=>x.endsWith('.cube')).sort()){
 const k=parseInt(name,10)-1;
 const c=eng.convertPreset('cube',readFileSync(lutDir+'/'+name,'utf8'),undefined,{hue:true,additiveHue:false,keepWhite:false});
 const old=inv.extras[k];
 const count=(a:any,b:any)=>Array.from(a??[]).filter((v,i)=>v!==Array.from(b??[])[i]).length;
 const differences={matrix:count(c.matrixQ13,old.matrixQ13),curves:c.curves.reduce((n,x,j)=>n+count(x,old.curves[j]),0),post:count(c.postQ9,old.postQ9),hue:count(c.hueQ10,old.hueQ10),huePresence:!!c.hueQ10!==!!old.hueQ10};
 imports.push({name,index:k+1,differences,meanDE2000:c.meanDE2000,p95DE2000:c.p95DE2000,preset:{matrixQ13:c.matrixQ13,curves:c.curves,postQ9:c.postQ9,hueQ10:c.hueQ10}});
 console.log(name,differences);
}
writeFileSync(out,norm({fitOptions:{hue:true,additiveHue:false,keepWhite:false},preserved,imports}));
