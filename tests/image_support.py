"""Generate small valid tile PNGs without external imaging dependencies."""
import struct
import zlib

def tile_png(width=256,height=59,color=3):
    raw=b''.join(b'\0'+bytes([color,80,140,255])*width for _ in range(height))
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
