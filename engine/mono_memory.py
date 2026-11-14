# Adapted from justfaked/hs-decktracker-linux@649534be99f35cb499ed2fae371625bd04b95b1d
# Copyright (c) 2026 justfaked. MIT: licenses/hs-decktracker-linux-MIT.txt.
# Local changes: version gates, mapped reads, bounds, cancellation and budgets.
# Profile provenance: Zero-to-Heroes/unity-spy-.net4.5 (Unity 6000.3 x64),
# and Unity-Technologies/mono unity-6000.1-mbe class-private-definition.h.
"""Optional read-only Unity 6000.3 x64 Mono reader. No remote calls or writes."""
from __future__ import annotations
import os
import struct
import time
from bisect import bisect_right
from pathlib import Path
from dataclasses import dataclass

# MonoDomain / MonoAssembly / MonoImage
DOMAIN_ASSEMBLIES = 160
ASSEMBLY_NAME = 16
ASSEMBLY_IMAGE = 96
IMAGE_CLASS_CACHE = 1232
HASH_TABLE_SIZE = 24
HASH_TABLE_TABLE = 32
# MonoClass
CLASS_KIND = 27
CLASS_INSTANCE_SIZE = 28  # Unity mono class-private-definition.h: x64 field after class_kind
CLASS_PARENT = 48
CLASS_NAME = 72
CLASS_NAMESPACE = 80
CLASS_VTABLE_SIZE = 92
CLASS_FIELDS = 152
CLASS_RUNTIME_INFO = 208
CLASS_GENERIC_CLASS = 240
CLASS_FIELD_COUNT = 256
CLASS_NEXT_CACHE = 264
FIELD_SIZE = 32
RUNTIME_INFO_VTABLES = 8
VTABLE_SLOTS = 72
# Managed objects
STRING_LENGTH = 16
STRING_CHARS = 20
ARRAY_LENGTH = 24
ARRAY_DATA = 32

CLASS_KIND_GINST = 3
FIELD_ATTR_STATIC = 0x10
FIELD_ATTR_LITERAL = 0x40

# MonoTypeEnum
T_BOOLEAN, T_CHAR, T_I1, T_U1, T_I2, T_U2, T_I4, T_U4, T_I8, T_U8, T_R4, T_R8, T_STRING = range(0x02, 0x0f)
T_VALUETYPE, T_CLASS, T_GENERICINST, T_OBJECT, T_SZARRAY = 0x11, 0x12, 0x15, 0x1c, 0x1d
REFERENCE_TYPES = {T_STRING, T_CLASS, T_GENERICINST, T_OBJECT, T_SZARRAY, 0x14}
PRIMITIVES = {
    T_BOOLEAN: "?", T_CHAR: "H", T_I1: "b", T_U1: "B", T_I2: "h", T_U2: "H", T_I4: "i",
    T_U4: "I", T_I8: "q", T_U8: "Q", T_R4: "f", T_R8: "d",
}


class MemoryReadError(Exception): pass
class UnsupportedLayout(MemoryReadError): pass
class MissingField(UnsupportedLayout): pass
class MonoMissing(MemoryReadError): pass
class NotReady(MemoryReadError): pass
class Cancelled(MemoryReadError): pass

class Process:
    def __init__(self,pid,proc=Path('/proc'),stop=None):
        self.pid=pid;self.root=Path(proc)/str(pid);self.stop=stop;self._fd=None
        self.maps=[];self.begin_poll(initial=True)
        self.refresh_maps()
        try:self._fd=os.open(self.root/'mem',os.O_RDONLY|getattr(os,'O_CLOEXEC',0))
        except Exception:self.close();raise

    def begin_poll(self,initial=False):
        self.deadline=time.monotonic()+(3 if initial else 1)
        self.bytes_read=0;self.reads=0

    def close(self):
        if self._fd is not None:
            fd,self._fd=self._fd,None;os.close(fd)

    def refresh_maps(self):
        regions=[]
        with (self.root/'maps').open() as f:
            for line in f:
                p=line.split(maxsplit=5)
                lo,hi=(int(v,16) for v in p[0].split('-'))
                if hi<=lo:raise UnsupportedLayout('invalid process mapping')
                regions.append((lo,hi,p[1],int(p[2],16),p[5].strip() if len(p)>5 else ''))
        self.maps=sorted(regions);self.starts=[r[0] for r in self.maps]

    def mapped(self,addr,size,permission='r'):
        if type(addr) is not int or type(size) is not int or addr<0x10000 or size<0 or addr+size>0x800000000000:return False
        end=addr+size;cursor=addr
        index=max(0,bisect_right(self.starts,addr)-1)
        for i in range(index,len(self.maps)):
            lo,hi,perms,_,_=self.maps[i]
            if lo<=cursor<hi and permission in perms:
                cursor=min(hi,end)
                if cursor==end:return True
            elif lo>cursor:break
        return False

    def read(self,addr,size):
        if self.stop is not None and self.stop.is_set():raise Cancelled('reader stopped')
        self.reads+=1;self.bytes_read+=size
        if time.monotonic()>self.deadline or self.reads>250000 or self.bytes_read>64*1024*1024:raise MemoryReadError('read budget exceeded')
        if size==0:return b''
        if size>1024*1024 or not self.mapped(addr,size):raise UnsupportedLayout('unmapped address or excessive read')
        if self._fd is None:raise MemoryReadError('memory descriptor closed')
        data=os.pread(self._fd,size,addr)
        if len(data)!=size:raise MemoryReadError('short process read')
        return data

    def unpack(self,fmt,addr):return struct.unpack('<'+fmt,self.read(addr,struct.calcsize('<'+fmt)))[0]
    def ptr(self,addr):return self.unpack('Q',addr)
    def i32(self,addr):return self.unpack('i',addr)
    def cstring(self,addr,limit=256):
        if not addr:return ''
        data=bytearray()
        while len(data)<limit:
            offset=len(data);size=min(64,limit-offset)
            if not self.mapped(addr+offset,size):size=1
            chunk=self.read(addr+offset,size)
            if b'\0' in chunk:return (data+chunk.split(b'\0',1)[0]).decode('utf-8',errors='strict')
            data.extend(chunk)
        raise UnsupportedLayout('unterminated native string')

    def module_base(self,filename):
        matches={lo for lo,_,_,offset,name in self.maps if offset==0 and name.lower().endswith('/'+filename.lower())}
        if len(matches)>1:raise UnsupportedLayout('ambiguous module mappings')
        return next(iter(matches),None)


def pe_image(p,base):
    if p.read(base,2)!=b'MZ':raise UnsupportedLayout('module is not PE')
    offset=p.unpack('I',base+0x3c)
    if not 0x40<=offset<=0x100000:raise UnsupportedLayout('invalid PE header offset')
    pe=base+offset
    if p.read(pe,4)!=b'PE\0\0' or p.unpack('H',pe+4)!=0x8664 or p.unpack('H',pe+24)!=0x20b:raise UnsupportedLayout('requires x86_64 PE32+')
    size=p.unpack('I',pe+24+56)
    if not 4096<=size<=256*1024*1024 or p.unpack('I',pe+24+108)<3:raise UnsupportedLayout('invalid PE image size/directories')
    return pe,size


def unity_version(p):
    base=p.module_base('unityplayer.dll')
    if base is None:raise UnsupportedLayout('UnityPlayer.dll version cannot be confirmed')
    pe,size=pe_image(p,base)
    rva,resource_size=struct.unpack('<II',p.read(pe+24+112+16,8))
    if not rva or not 16<=resource_size<=4*1024*1024 or rva+resource_size>size:raise UnsupportedLayout('missing Unity version resource')
    root=base+rva
    def entries(offset):
        if offset<0 or offset+16>resource_size:raise UnsupportedLayout('invalid version resource tree')
        count=p.unpack('H',root+offset+12)+p.unpack('H',root+offset+14)
        if count>256 or offset+16+count*8>resource_size:raise UnsupportedLayout('excessive version resources')
        return [struct.unpack('<II',p.read(root+offset+16+i*8,8)) for i in range(count)]
    types=[v for name,v in entries(0) if name==16]
    if len(types)!=1 or not types[0]&0x80000000:raise UnsupportedLayout('missing version type')
    nodes=[types[0]&0x7fffffff];leaves=[];visited=set()
    for _ in range(3):
        children=[]
        for node in nodes:
            if node in visited or len(visited)>=512:raise UnsupportedLayout('version resource cycle/excessive nodes')
            visited.add(node)
            for _,value in entries(node):
                if value&0x80000000:children.append(value&0x7fffffff)
                else:leaves.append(value)
                if len(leaves)>512:raise UnsupportedLayout('excessive version leaves')
        nodes=children
    versions=set()
    for leaf in leaves:
        if leaf+16>resource_size:raise UnsupportedLayout('invalid version leaf')
        data_rva,length=struct.unpack('<II',p.read(root+leaf,8))
        if not 52<=length<=65536 or data_rva+length>size:raise UnsupportedLayout('invalid version data')
        data=p.read(base+data_rva,length);marker=data.find(b'\xbd\x04\xef\xfe')
        if marker<0 or marker%4 or marker+52>len(data) or struct.unpack_from('<I',data,marker+4)[0]!=0x10000:raise UnsupportedLayout('missing VS_FIXEDFILEINFO')
        ms,ls=struct.unpack_from('<II',data,marker+8)
        versions.add((ms>>16,ms&65535,ls>>16,ls&65535))
    if len(versions)!=1:raise UnsupportedLayout('ambiguous Unity version')
    version=versions.pop()
    if version[:2]!=(6000,3):raise UnsupportedLayout('unsupported Unity version '+'.'.join(map(str,version)))
    return version

@dataclass(frozen=True)
class Field:
    name: str
    type: int
    offset: int
    static: bool
    type_data: int  # MonoType.data (class / generic class pointer)


class Mono:
    """The Mono runtime inside a Hearthstone process."""

    def __init__(self, process: Process, assembly: str = "Assembly-CSharp"):
        self.p = process
        base = process.module_base("mono-2.0-bdwgc.dll")
        if base is None:
            raise MonoMissing("mono-2.0-bdwgc.dll is not loaded")
        self.version=unity_version(process)
        func = self._export(base, b"mono_get_root_domain")
        # x64: mov rax, [rip+disp32]; ret
        if self.p.read(func, 3) != b"\x48\x8b\x05" or self.p.read(func+7,1)!=b"\xc3" or not self.p.mapped(func,8,'x'):
            raise UnsupportedLayout("unexpected mono_get_root_domain code")
        self.domain = self.p.ptr(func + 7 + self.p.i32(func + 3))
        if not self.domain:raise NotReady('Mono root domain not initialized')
        self.image = self._assembly_image(assembly)
        self._classes: dict[str, int] | None = None
        self._fields: dict[int, dict[str, Field]] = {}

    def _export(self, base: int, name: bytes) -> int:
        pe,size=pe_image(self.p,base)
        def rva(offset,length=1):
            value=self.p.unpack('I',offset)
            if value<0x100 or value+length>size:raise UnsupportedLayout('invalid export RVA')
            return base+value
        exports=rva(pe+0x18+0x70,40)
        count=self.p.unpack('I',exports+0x18);functions_count=self.p.unpack('I',exports+0x14)
        if not 1<=count<=65536 or not 1<=functions_count<=65536:raise UnsupportedLayout('invalid export count')
        functions=rva(exports+0x1c,4*functions_count);names=rva(exports+0x20,4*count);ordinals=rva(exports+0x24,2*count)
        for i in range(count):
            if self.p.cstring(rva(names+4*i),256).encode()==name:
                ordinal=self.p.unpack('H',ordinals+2*i)
                if ordinal>=functions_count:raise UnsupportedLayout('invalid export ordinal')
                return rva(functions+4*ordinal,8)
        raise UnsupportedLayout('required Mono export missing')

    def _assembly_image(self, name: str) -> int:
        node = self.p.ptr(self.domain + DOMAIN_ASSEMBLIES)
        seen=set()
        for _ in range(1000):
            if not node:
                break
            if node in seen:raise UnsupportedLayout("assembly list cycle")
            seen.add(node)
            assembly = self.p.ptr(node)
            if assembly and self.p.cstring(self.p.ptr(assembly + ASSEMBLY_NAME), 64) == name:
                image=self.p.ptr(assembly + ASSEMBLY_IMAGE)
                if not image:raise NotReady("Assembly-CSharp image not initialized")
                return image
            node = self.p.ptr(node + 8)
        raise NotReady(f"assembly {name} not loaded")

    # -- classes ------------------------------------------------------------------

    def classes(self) -> dict[str, int]:
        """All classes of the assembly by full name (namespace.Name)."""
        if self._classes is None:
            cache = self.image + IMAGE_CLASS_CACHE
            size = self.p.unpack("I", cache + HASH_TABLE_SIZE)
            if not 1<=size<=131072:raise UnsupportedLayout("invalid class cache size")
            table = self.p.ptr(cache + HASH_TABLE_TABLE)
            buckets = struct.unpack(f"<{size}Q", self.p.read(table, 8 * size))
            classes = {};seen=set()
            for klass in buckets:
                while klass:
                    if klass in seen or len(seen)>=65536:raise UnsupportedLayout("class cache cycle or excessive size")
                    seen.add(klass)
                    name = self.p.cstring(self.p.ptr(klass + CLASS_NAME), 128)
                    namespace = self.p.cstring(self.p.ptr(klass + CLASS_NAMESPACE), 128)
                    if not name or any(ord(c)<32 for c in name+namespace):raise UnsupportedLayout("invalid managed class name")
                    classes[f"{namespace}.{name}" if namespace else name] = klass
                    klass = self.p.ptr(klass + CLASS_NEXT_CACHE)
            self._classes = classes
        return self._classes

    def find_class(self, full_name: str) -> int:
        klass = self.classes().get(full_name)
        if klass is None:
            raise UnsupportedLayout(f"class {full_name} not found in layout profile")
        return klass

    def fields(self, klass: int) -> dict[str, Field]:
        """Fields of a class including inherited ones."""
        if klass in self._fields:
            return self._fields[klass]
        out: dict[str, Field] = {}
        current = klass
        parents=set()
        for _ in range(32):
            if not current:
                break
            if current in parents:raise UnsupportedLayout("class inheritance cycle")
            parents.add(current)
            definition = current
            if self.p.unpack("B", current + CLASS_KIND) & 0x7 == CLASS_KIND_GINST:
                # Generic instances share the field layout of their generic definition.
                definition = self.p.ptr(self.p.ptr(current + CLASS_GENERIC_CLASS))
            fields_ptr = self.p.ptr(definition + CLASS_FIELDS)
            count = self.p.i32(definition + CLASS_FIELD_COUNT)
            if not 0<=count<=4096 or (count and not fields_ptr):raise UnsupportedLayout("invalid field count")
            for i in range(count if fields_ptr else 0):
                f = fields_ptr + i * FIELD_SIZE
                type_ptr = self.p.ptr(f)
                name = self.p.cstring(self.p.ptr(f + 8), 128)
                if not name or any(ord(c)<32 for c in name):raise UnsupportedLayout("invalid managed field name")
                attrs = self.p.unpack("H", type_ptr + 8)
                if attrs & FIELD_ATTR_LITERAL or name in out:
                    continue
                offset=self.p.i32(f+24)
                if not 0<=offset<=1024*1024:raise UnsupportedLayout("invalid field offset")
                out[name] = Field(name=name, type=self.p.unpack("B", type_ptr + 10),
                                  offset=self.p.i32(f + 24), static=bool(attrs & FIELD_ATTR_STATIC),
                                  type_data=self.p.ptr(type_ptr))
            current = self.p.ptr(current + CLASS_PARENT)
        if current:raise UnsupportedLayout("excessive inheritance depth")
        self._fields[klass] = out
        return out

    def static(self, class_name: str, field_name: str):
        klass = self.find_class(class_name)
        field = self.fields(klass).get(field_name)
        if field is None or not field.static:raise UnsupportedLayout("required static field missing")
        runtime_info = self.p.ptr(klass + CLASS_RUNTIME_INFO)
        if not runtime_info:
            return None  # class not initialised yet
        vtable = self.p.ptr(runtime_info + RUNTIME_INFO_VTABLES)
        if not vtable:
            return None
        slots=self.p.i32(klass+CLASS_VTABLE_SIZE)
        if not 0<=slots<=8192 or self.p.ptr(vtable)!=klass:raise UnsupportedLayout("invalid class vtable")
        data = self.p.ptr(vtable + VTABLE_SLOTS + 8 * slots)
        return self._value(data + field.offset, field.type) if data else None

    # -- objects ------------------------------------------------------------------

    def _value(self, addr: int, kind: int):
        if kind in PRIMITIVES:
            return self.p.unpack(PRIMITIVES[kind], addr)
        if kind == T_VALUETYPE:  # enums and small structs: read as int
            return self.p.i32(addr)
        if kind in REFERENCE_TYPES:
            ref = self.p.ptr(addr)
            if not ref:
                return None
            return self.string(ref) if kind == T_STRING else Obj(self, ref)
        raise UnsupportedLayout("unsupported field type")

    def string(self, addr: int) -> str:
        length = self.p.i32(addr + STRING_LENGTH)
        if not 0 <= length <= 4096:
            raise UnsupportedLayout("implausible string length")
        return self.p.read(addr + STRING_CHARS, 2 * length).decode("utf-16-le", errors="strict")

    def class_name(self, klass: int) -> str:
        return self.p.cstring(self.p.ptr(klass + CLASS_NAME), 128)


class Obj:
    """A managed object; obj["m_field"] reads a field."""

    def __init__(self, mono: Mono, addr: int):
        if not addr or addr%8 or not mono.p.mapped(addr,16):raise UnsupportedLayout("invalid managed object pointer")
        self.mono = mono
        self.addr = addr
        self._klass: int | None = None

    @property
    def klass(self) -> int:
        if self._klass is None:  # looked up lazily: arrays are read without it
            klass = self.mono.p.ptr(self.mono.p.ptr(self.addr))  # MonoObject.vtable -> MonoVTable.klass
            size=self.mono.p.i32(klass+CLASS_INSTANCE_SIZE)
            if not 16<=size<=1024*1024 or not self.mono.p.mapped(self.addr,size):raise UnsupportedLayout("invalid managed instance size")
            self._klass=klass
        return self._klass

    @property
    def class_name(self) -> str:
        return self.mono.class_name(self.klass)

    def __getitem__(self, name: str):
        field = self.mono.fields(self.klass).get(name)
        if field is None:
            raise MissingField(f"{self.class_name} has no field {name}")
        width=struct.calcsize(PRIMITIVES[field.type]) if field.type in PRIMITIVES else 4 if field.type==T_VALUETYPE else 8
        if field.static or field.offset<16 or field.offset+width>self.mono.p.i32(self.klass+CLASS_INSTANCE_SIZE):raise UnsupportedLayout("field exceeds instance boundary")
        return self.mono._value(self.addr + field.offset, field.type)

    def get(self, name: str, default=None):
        try:
            return self[name]
        except MissingField:
            return default

    # Arrays and List<T>
    @property
    def length(self) -> int:
        length = self.mono.p.ptr(self.addr + ARRAY_LENGTH)
        if length > 4096:
            raise UnsupportedLayout("implausible array length")
        return length

    def element_addr(self, index: int, size: int) -> int:
        if type(index) is not int or not 0<=index<self.length or size not in (4,8,24):raise UnsupportedLayout("invalid array index or element size")
        return self.addr + ARRAY_DATA + index * size

    def array_refs(self) -> list[int]:
        n = self.length
        return list(struct.unpack(f"<{n}Q", self.mono.p.read(self.addr + ARRAY_DATA, 8 * n)))

    def array_ints(self) -> list[int]:
        n = self.length
        return list(struct.unpack(f"<{n}i", self.mono.p.read(self.addr + ARRAY_DATA, 4 * n)))

    def _list(self,limit):
        size,items=self['_size'],self['_items']
        if type(size) is not int or not 0<=size<=limit:raise UnsupportedLayout('invalid list size')
        if not items:
            if size:raise UnsupportedLayout('missing list storage')
            return 0,None
        if size>items.length:raise UnsupportedLayout('list size exceeds capacity')
        return size,items

    def list_objects(self,limit=512):
        size,items=self._list(limit)
        if not size:return []
        refs=struct.unpack(f'<{size}Q',self.mono.p.read(items.addr+ARRAY_DATA,8*size))
        if any(not r or r%8 for r in refs):raise UnsupportedLayout('invalid list object pointer')
        return [Obj(self.mono,r) for r in refs]

    def list_strings(self,limit=100):
        return [self.mono.string(o.addr) for o in self.list_objects(limit)]

    def list_ints(self,limit=100):
        size,items=self._list(limit)
        return list(struct.unpack(f'<{size}i',self.mono.p.read(items.addr+ARRAY_DATA,4*size))) if size else []
