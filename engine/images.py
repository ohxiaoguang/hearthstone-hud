"""CRC/deflate-validated HearthstoneJSON 256x59 tile storage."""
import os
from pathlib import Path
import re
import struct
import tempfile
import zlib

MAX_IMAGE=1024*1024


def valid_id(cid):
    return isinstance(cid,str) and bool(re.fullmatch(r'(?=.*[A-Za-z])[A-Za-z0-9_]{1,128}',cid))


def validate_png(data, full=False):
    if len(data)>(4*MAX_IMAGE if full else MAX_IMAGE) or data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('PNG 文件头或大小错误')
    pos=8;chunks=[];compressed=bytearray();header=None;palette=False;ended=False
    while pos<len(data):
        if pos+12>len(data):raise ValueError('PNG 数据截断')
        size=struct.unpack_from('>I',data,pos)[0];kind=data[pos+4:pos+8];pos+=8
        if size>(4*MAX_IMAGE if full else MAX_IMAGE) or pos+size+4>len(data):raise ValueError('PNG chunk 超限或截断')
        payload=data[pos:pos+size];crc=struct.unpack_from('>I',data,pos+size)[0];pos+=size+4
        if zlib.crc32(kind+payload)&0xffffffff!=crc:raise ValueError('PNG CRC 校验失败')
        if not chunks and kind!=b'IHDR':raise ValueError('缺少 PNG IHDR')
        chunks.append(kind)
        if kind==b'IHDR':
            if header or size!=13:raise ValueError('PNG IHDR 错误')
            header=struct.unpack('>IIBBBBB',payload)
        elif kind==b'PLTE':palette=True
        elif kind==b'IDAT':compressed.extend(payload)
        elif kind==b'IEND':
            if size or pos!=len(data):raise ValueError('PNG IEND/尾部错误')
            ended=True;break
        elif not kind[0]&32:raise ValueError('不支持的 PNG critical chunk')
    if not header or not ended or not compressed:raise ValueError('PNG 不完整')
    width,height,depth,color,compression,filtering,interlace=header
    channels={0:1,2:3,3:1,4:2,6:4}.get(color)
    if full:
        if not (128 <= width <= 1024 and 128 <= height <= 1536):raise ValueError('Invalid full card dimensions')
    elif (width,height)!=(256,59):raise ValueError('仅接受 256x59 卡图缩略 PNG')
    allowed=(1,2,4,8) if color==3 else (1,2,4,8,16) if color==0 else (8,16)
    if not channels or depth not in allowed or compression or filtering or interlace not in (0,1) or (color==3 and not palette):raise ValueError('PNG 编码错误')
    passes=[(0,0,1,1)] if not interlace else [(0,0,8,8),(4,0,8,8),(0,4,4,8),(2,0,4,4),(0,2,2,4),(1,0,2,2),(0,1,1,2)]
    rows=[]
    for x,y,dx,dy in passes:
        w=max(0,(width-x+dx-1)//dx);h=max(0,(height-y+dy-1)//dy)
        if w and h:rows.extend([1+(w*depth*channels+7)//8]*h)
    expected=sum(rows);decoder=zlib.decompressobj()
    try:raw=decoder.decompress(bytes(compressed),expected+1)
    except zlib.error as exc:raise ValueError('PNG 解压失败') from exc
    if len(raw)!=expected or not decoder.eof or decoder.unused_data:raise ValueError('PNG 像素数据损坏或解压超限')
    offset=0
    for length in rows:
        if raw[offset]>4:raise ValueError('PNG filter 错误')
        offset+=length
    return True


def atomic_image(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.tile-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data)
        os.chmod(tmp,0o600);os.replace(tmp,path)
    finally:Path(tmp).unlink(missing_ok=True)


class TileStore:
    def __init__(self,root):
        self.root=Path(root)
        self._checked={}

    def valid_file(self,path):
        try:
            if path.is_symlink():return False
            st=path.stat();key=(str(path),st.st_mtime_ns,st.st_size)
            if key in self._checked:return self._checked[key]
            with path.open('rb') as f:validate_png(f.read(MAX_IMAGE+1))
            if len(self._checked)>2048:self._checked.clear()
            self._checked[key]=True;return True
        except (OSError,ValueError,zlib.error):
            if 'key' in locals():
                if len(self._checked)>2048:self._checked.clear()
                self._checked[key]=False
            return False

    def exists(self,cid):
        """Cheap presence check for batching; `path()` still validates the PNG."""
        if not valid_id(cid):return False
        return (self.root/(cid+'.png')).is_file()

    def path(self,cid):
        if not valid_id(cid):return None
        p=self.root/(cid+'.png')
        return p if self.valid_file(p) else None

    def counts(self):
        return dict(automatic=sum(1 for p in self.root.glob('*.png') if self.valid_file(p)))
