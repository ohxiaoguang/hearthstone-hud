#!/usr/bin/env python3
"""Inspect ELF and optionally resolve dependency files; does not execute Linux ldd."""
import argparse
from pathlib import Path
import re
import struct


def inspect(path):
    data=Path(path).read_bytes()
    assert len(data)>=64 and data[:7]==b'\x7fELF\x02\x01\x01','Expected little-endian ELF64'
    h=struct.unpack_from('<16sHHIQQQIHHHHHH',data)
    assert h[1] in (2,3) and h[2]==62,'Expected x86_64 executable/PIE'
    shoff,entsize,num,string_index=h[6],h[11],h[12],h[13]
    assert entsize==64 and shoff+entsize*num<=len(data),'Invalid section table'
    headers=[struct.unpack_from('<IIQQQQIIQQ',data,shoff+i*entsize) for i in range(num)]
    def content(header):
        offset,size=header[4],header[5]
        assert offset+size<=len(data),'Section out of file bounds'
        return data[offset:offset+size]
    names=content(headers[string_index])
    def string(table,pos):return table[pos:].split(b'\0',1)[0].decode('utf-8')
    sections={string(names,sh[0]):content(sh) for sh in headers if sh[1]!=8}
    strings=sections.get('.dynstr',b'');needed=[];paths=[]
    dynamic=sections.get('.dynamic',b'')
    for offset in range(0,len(dynamic),16):
        tag,value=struct.unpack_from('<QQ',dynamic,offset)
        if tag==1:needed.append(string(strings,value))
        if tag in (15,29):paths.append(string(strings,value))
    versions={tuple(map(int,m)) for m in re.findall(rb'GLIBC_(\d+)\.(\d+)',strings)}
    return dict(needed=needed,paths=paths,versions=versions,interpreter=sections.get('.interp',b'').rstrip(b'\0').decode())


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('binary');parser.add_argument('--sysroot',type=Path)
    args=parser.parse_args();meta=inspect(args.binary)
    assert meta['versions'] and max(meta['versions'])<=(2,31),'GLIBC baseline exceeds 2.31'
    assert not meta['paths'],'Unexpected RPATH/RUNPATH'
    assert meta['interpreter']=='/lib64/ld-linux-x86-64.so.2','Unexpected Linux interpreter'
    print('ELF64 Linux x86_64; GLIBC maximum:',max(meta['versions']))
    print('DT_NEEDED:',', '.join(meta['needed']))
    if args.sysroot:
        pending=list(meta['needed']);checked=set()
        roots=[args.sysroot/p for p in ('usr/lib/x86_64-linux-gnu','lib/x86_64-linux-gnu','lib64')]
        while pending:
            name=pending.pop()
            if name in checked:continue
            target=next((root/name for root in roots if (root/name).is_file()),None)
            assert target is not None,'Unresolved dependency in sysroot: '+name
            checked.add(name);pending.extend(inspect(target)['needed'])
        print('Static dependency closure resolved:',', '.join(sorted(checked)))
    print('This is static inspection; Linux ldd/runtime execution is not claimed.')


if __name__=='__main__':main()
