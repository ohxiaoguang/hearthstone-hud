"""Discover only live Hearthstone processes; never infer a prefix from old files."""
import os
from pathlib import Path, PureWindowsPath

ENV_KEYS = ('STEAM_COMPAT_DATA_PATH', 'WINEPREFIX', 'SteamAppId', 'DISPLAY')


def linux_game_dir(args):
    for arg in args:
        value = arg.strip('"')
        path = PureWindowsPath(value)
        if path.name.lower() != 'hearthstone.exe':
            continue
        if path.drive.lower() == 'z:' and path.root:
            return str(Path('/').joinpath(*path.parts[1:]).parent)
        if value.startswith('/'):
            return str(Path(value).parent)
    return ''


def user_directory(prefix):
    users = Path(prefix)/'drive_c/users'
    try:
        profiles = [p for p in users.iterdir() if p.is_dir() and p.name.lower() not in
                    ('public','default','default user','all users') and (p/'AppData/Local').is_dir()]
    except OSError:
        return '', '未发现可读取的 Windows 用户目录'
    homes = [p/'AppData/Local/Blizzard/Hearthstone' for p in profiles]
    existing = [p for p in homes if p.is_dir()]
    if len(existing) == 1:
        return str(existing[0]), ''
    if len(existing) > 1:
        return '', '多个 Hearthstone 用户目录，无法唯一确定；未写入配置'
    if len(homes) == 1:
        return str(homes[0]), ''
    return '', '无法唯一确定 Windows 用户目录；未写入配置'


def discover_process(proc=Path('/proc')):
    matches, errors = [], []
    try:
        entries = sorted((p for p in Path(proc).iterdir() if p.name.isdigit()), key=lambda p:int(p.name))
    except OSError as exc:
        return dict(found=False,error=str(exc))
    for entry in entries:
        if int(entry.name) == os.getpid():
            continue
        comm = ''
        is_game = False
        try:
            comm = (entry/'comm').read_text().strip().lower()
            args = [s.decode('utf-8',errors='replace') for s in (entry/'cmdline').read_bytes()[:65536].split(b'\0') if s]
            def executable(arg):
                return PureWindowsPath(arg.strip('"')).name.lower() == 'hearthstone.exe'
            is_game = comm == 'hearthstone.exe' or (bool(args) and executable(args[0])) or (comm.startswith('wine') and any(executable(a) for a in args))
            if not is_game:
                continue
            # Do not expose unrelated environment variables, credentials, or command lines.
            values = {}
            for item in (entry/'environ').read_bytes()[:1024*1024].split(b'\0'):
                key,sep,value = item.partition(b'=')
                name = key.decode('utf-8',errors='replace')
                if sep and name in ENV_KEYS:
                    values[name] = value.decode('utf-8',errors='replace')
            prefix = ''
            for value in (values.get('WINEPREFIX',''), str(Path(values['STEAM_COMPAT_DATA_PATH'])/'pfx') if values.get('STEAM_COMPAT_DATA_PATH') else ''):
                path = Path(value)
                if value and path.is_absolute() and path.is_dir() and (path/'drive_c').is_dir():
                    prefix = str(path)
                    break
            home,error = user_directory(prefix) if prefix else ('','运行时环境中没有有效 Proton 前缀')
            try:
                start = (entry/'stat').read_text().rsplit(')',1)[1].split()[19]
            except (OSError,IndexError):
                start = ''
            matches.append(dict(found=True,instance=entry.name+':'+start,pid=int(entry.name),cmdline=args,environment=values,
                                prefix=prefix,user_dir=home,game_dir=linux_game_dir(args),error=error))
        except (OSError,ValueError) as exc:
            # Permission failures for non-game processes are normal on /proc.
            if is_game:
                matches.append(dict(found=True,pid=int(entry.name),cmdline=args,prefix='',user_dir='',error='无法读取游戏进程环境：'+str(exc)))
    prefixes = {m['prefix'] for m in matches if m['prefix']}
    if len(prefixes)>1:
        return dict(found=True,error='多个游戏进程使用不同前缀，未自动配置',prefix='',user_dir='')
    if matches:
        return max(matches,key=lambda m:(bool(m.get('prefix')),bool(m.get('game_dir'))))
    return dict(found=False,error='游戏进程未发现' if not errors else '无法读取游戏进程环境：'+'; '.join(errors))
