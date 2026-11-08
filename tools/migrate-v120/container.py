# SPDX-License-Identifier: GPL-2.0-only
"""Independent Python LZ/container verification; no TypeScript or firmware tool imports."""
import argparse,array,hashlib,json,struct,sys
from pathlib import Path

def sum32(b):
    words=array.array('I');words.frombytes(b[:len(b)//4*4])
    if sys.byteorder!='little':words.byteswap()
    return (sum(words)+int.from_bytes(b[len(words)*4:],'little'))&0xffffffff

def decode(raw):
    out=bytearray();p=128;frames=[]
    while True:
        prefix=int.from_bytes(raw[p:p+2],'big');p+=2
        if prefix==0:break
        end=p+(prefix&0x7fff);start=len(out)
        assert end<=len(raw)-24
        if prefix&0x8000:out.extend(raw[p:end])
        else:
            while p<end:
                flags=int.from_bytes(raw[p:p+2],'big');p+=2
                for bit in range(15,-1,-1):
                    if p>=end:break
                    if not flags&(1<<bit):out.append(raw[p]);p+=1;continue
                    x,y=raw[p:p+2];p+=2;dist=((x&0xf8)<<5)+y;n=x&7
                    if n==7:
                        while True:
                            v=raw[p];p+=1;n+=v
                            if v!=255:break
                    if not dist:break
                    assert dist<=len(out)
                    n+=3;pattern=out[-dist:];out.extend((pattern*((n+dist-1)//dist))[:n])
        p=end;frames.append(len(out)-start)
    assert sum32(raw)==0 and sum32(out)==0
    proj=struct.unpack_from('<I',raw,0x30)[0];p2=proj|(proj<<16)
    fproj,magic,typ,clen,dlen,checksum=struct.unpack_from('<6I',raw,len(raw)-24)
    assert fproj==p2 and magic==0xa55a5aa5
    assert struct.unpack_from('<2I',raw,0x78)==(p2,0xa55a5aa5)
    assert clen==p-128 and dlen==len(out)
    models=raw[(p+3)&~3:-24]
    assert len(models)%128==0
    return bytes(out),models,frames

def sections(b):
    out=[];p=0
    while p+16<=len(b):
        name=b[p:p+8].rstrip(b'\0').decode('ascii');v1,v2,n=struct.unpack_from('<HHI',b,p+8)
        assert name
        length=len(b)-p-16 if name=='RES' else n
        out.append((name,v1,v2,n,p+16,b[p+16:p+16+length]))
        if name=='RES':break
        p+=16+n
    return out

ap=argparse.ArgumentParser();ap.add_argument('official',type=Path);ap.add_argument('candidate',type=Path);ap.add_argument('out',type=Path);a=ap.parse_args()
old=a.official.read_bytes();new=a.candidate.read_bytes();od,om,of=decode(old);nd,nm,nf=decode(new)
assert old[:128]==new[:128] and om==nm
os,ns=sections(od),sections(nd)
assert len(os)==len(ns)
result=[]
(a.out/'official120.icons').write_bytes(next(x[5] for x in os if x[0]=='ICONBIN'))
for x,y in zip(os,ns):
    name,v1,v2,n,p,b=x;nn,vv1,vv2,sz,np,bb=y
    assert (name,v1,v2)==(nn,vv1,vv2)
    same=b==bb
    if name not in ('RTOS','ICONBIN'):assert same and n==sz,name
    else:assert (sz-n)%0x6000==0 and sz>=n
    result.append({'name':name,'oldSize':n,'newSize':sz,'unchanged':same})
assert nd[-4:]==od[-4:]
r=next(y for y in ns if y[0]=='RTOS')
assert r[5]==(a.out/'120-final.rtos').read_bytes()
report={'sha256':hashlib.sha256(new).hexdigest(),'fileBytes':len(new),'decodedBytes':len(nd),'officialFileSum':sum32(old),'newFileSum':sum32(new),'officialDecodedSum':sum32(od),'newDecodedSum':sum32(nd),'headerIdentical':True,'modelRecordsIdentical':True,'decodedLastWordIdentical':True,'sections':result,'frameCount':[len(of),len(nf)],'rtosMatchesTestedImage':True}
(a.out/'container-audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
