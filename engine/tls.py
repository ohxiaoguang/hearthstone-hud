"""Supplement embedded Python CA discovery without changing system trust or SSL policy."""
from pathlib import Path
import ssl
import threading

_modules=Path(__file__).resolve().parent.parent
ROOT=_modules.parent if _modules.name=='py_modules' else _modules
BUNDLE=ROOT/'assets/certs/cacert.pem'
SYSTEM_CA_FILES=(Path('/etc/ssl/certs/ca-certificates.crt'),Path('/etc/ssl/cert.pem'),Path('/etc/ca-certificates/extracted/tls-ca-bundle.pem'))
_lock=threading.Lock()
_context=None
_status=dict(state='尚未初始化',ca_count=0,sources=[],errors=[])


def build_context():
    context=ssl.create_default_context()
    sources=['OpenSSL 默认信任库'];errors=[]
    for path in (*SYSTEM_CA_FILES,BUNDLE):
        if not path.is_file():continue
        try:
            context.load_verify_locations(cafile=str(path));sources.append(str(path))
        except (OSError,ssl.SSLError) as exc:
            errors.append(str(path)+': '+str(exc))
    assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
    count=context.cert_store_stats()['x509_ca']
    if not count:raise ssl.SSLError('没有可用的 CA 证书；证书校验不会关闭，请重新安装完整插件 ZIP')
    return context,dict(state='证书与主机名校验开启',ca_count=count,sources=sources,errors=errors)


def verified_context():
    global _context,_status
    with _lock:
        if _context is None:_context,_status=build_context()
        return _context


def diagnostic():
    with _lock:return dict(_status)
