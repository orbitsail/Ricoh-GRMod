# SPDX-License-Identifier: GPL-2.0-only
"""Independent RTOS audit of actual built shadow-on/off containers' extracted images."""
import argparse,base64,hashlib,json,re,struct
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('out',type=Path);ap.add_argument('--version',choices=['111','120'],default='120');a=ap.parse_args();out=a.out;v=a.version
root=Path(__file__).resolve().parents[2]
module_root=root/'core/src/fw'/('gr4v120/aspect' if v=='120' else 'aspect')
base=(out/f'{v}-awb.rtos').read_bytes();new=(out/f'{v}-final.rtos').read_bytes();B=0x53000000
hook,gain,slot,alloc,scratch=(0x539473a4,0x54080044,0x5583903c,0x539084bc,0x55839014) if v=='120' else (0x5391f3a4,0x5404938c,0x558372fc,0x538e09b0,0x558372d4)
word=lambda b,p:struct.unpack_from('<I',b,p-B)[0]
def dest(p,w):return p+8+((w&0xffffff)-(0x1000000 if w&0x800000 else 0))*4
st=dest(hook,word(new,hook))
def imm(p):w=word(new,p);return ((w>>4)&0xf000)|(w&0xfff)
ctx=imm(st+32)|(imm(st+36)<<16)
# Find the one BL to the module in the fixed verified stub.
calls=[(p,dest(p,word(new,p))) for p in range(st,st+88,4) if word(new,p)>>24==0xeb]
assert len(calls)==1,calls
code=calls[0][1]
blob=word(new,ctx+4);nblob=word(new,ctx+8)
def generated(name,ident):
 s=(module_root/name).read_text();return base64.b64decode(re.search(r'export const '+ident+r" = '([^']+)'",s)[1])
cb=generated('shadowml-code.ts','SHADOWML_CODE');db=generated('shadowml-data.ts','SHADOWML_DATA')
assert new[code-B:code-B+len(cb)]==cb
assert new[blob-B:blob-B+nblob]==db
assert struct.unpack_from('<7I',new,ctx-B)==(0x4c444853,blob,len(db),4,slot,alloc,scratch)
assert word(base,hook)==0xe51b2450 and word(base,gain)==0x100 and word(new,gain)==0x400
assert ctx%16==0 and code%16==0 and blob%16==0
# The exact recipe is independently decoded; only shadow bit 1 may change.
def record(b):
 assert b[-12:-4]==b'GRMODAR3'
 n=struct.unpack_from('<I',b,len(b)-16)[0];off=len(b)-16-n
 return off,b[off:off+n]
ra,arec=record(base);rb,brec=record(new)
assert len(arec)==len(brec)
rchanges=[(i,x,y) for i,(x,y) in enumerate(zip(arec,brec)) if x!=y]
assert len(rchanges)==1 and rchanges[0][1]^rchanges[0][2]==2,rchanges
# Builder packs a trailing second-feature marker and learned byte; actual recipe must
# match known option mask (AWB + fit + balanced =21; add shadow =23).
assert rchanges[0][1:]==(21,23),rchanges
end=blob-B+len(db)
assert base[ctx-B:ra]==bytes(ra-(ctx-B))
assert new[end:rb]==bytes(rb-end)
allow=lambda i:(hook-B<=i<hook-B+4 or gain-B<=i<gain-B+4 or ctx-B<=i<end or rb<=i or i>=ra)
# Full old prefix up to appended shadow area must be identical outside its two hooks.
outside=[i for i in range(ctx-B) if base[i]!=new[i] and not allow(i)]
assert not outside,outside[:10]
assert len(new)>=len(base)
report={'baseSha256':hashlib.sha256(base).hexdigest(),'newSha256':hashlib.sha256(new).hexdigest(),'verified':True,'outside':len(outside),'ctx':hex(ctx),'code':hex(code),'stub':hex(st),'blob':hex(blob),'codeBytes':len(cb),'modelBytes':len(db),'recipeChanges':rchanges,'lengths':[len(base),len(new)]}
(out/('shadow-diff.json' if v=='120' else 'shadow111-diff.json')).write_text(json.dumps(report,indent=2))
# Bind the actual AWB module and all its tables to the regenerated source blobs too.
ah=0x53960e90 if v=='120' else 0x53938e2c;ast=dest(ah,word(new,ah))
actx=imm(ast+12)|(imm(ast+16)<<16);acode=dest(ast+32,word(new,ast+32));adata=word(new,actx+12)
ac=generated('awbml-code.ts','AWBML_CODE');ad=generated('awbml-data.ts','AWBML_DATA')
assert new[acode-B:acode-B+len(ac)]==ac
assert new[adata-B:adata-B+len(ad)]==ad
assert [word(new,actx+4*k) for k in [0,1,2,16,17,18,19]]==[0x4d425741,alloc,0x5583901c if v=='120' else 0x558372dc,4,1,2,1]
awb={'imageSha256':hashlib.sha256(new).hexdigest(),'code':hex(acode),'ctx':hex(actx),'stub':hex(ast),'data':hex(adata),'codeBytes':len(ac),'tableBytes':len(ad),'codeMatchesGenerated':True,'tablesMatchGenerated':True}
(out/('awb-layout.json' if v=='120' else 'awb111-layout.json')).write_text(json.dumps(awb,indent=2))

print(report)
