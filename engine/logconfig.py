"""Atomic, backed-up Power-only edits in the currently discovered live prefix."""
import configparser
import os
from pathlib import Path
import re
import tempfile

POWER = dict(LogLevel='1',FilePrinting='True',ConsolePrinting='False',ScreenPrinting='False',Verbose='True')


def inspect_config(user_dir):
    if not user_dir:
        return dict(path='',exists=False,enabled=False,state='Hearthstone 用户目录未发现')
    path = Path(user_dir)/'log.config'
    result = dict(path=str(path),exists=path.exists(),enabled=False,state='log.config 不存在')
    if not result['exists']:
        return result
    try:
        parser=configparser.ConfigParser(interpolation=None)
        parser.read_string(path.read_text(encoding='utf-8-sig'))
        section=next((s for s in parser.sections() if s.lower()=='power'),None)
        result['enabled']=bool(section and all(parser.get(section,k,fallback='').strip().lower()==v.lower() for k,v in POWER.items()))
        result['state']='Power 配置已启用' if result['enabled'] else 'Power 配置未启用'
    except (OSError,ValueError,configparser.Error) as exc:
        result['state']='配置无法解析：'+str(exc)
        result['error']=str(exc)
    return result


def ensure_power(process):
    if not process.get('found') or not process.get('prefix') or not process.get('user_dir'):
        return dict(path='',exists=False,enabled=False,success=False,changed=False,restart_required=False,
                    state=process.get('error') or 'Proton 前缀未发现')
    directory=Path(process['user_dir'])
    # Refuse paths escaping the discovered prefix (including existing symlinks).
    prefix=Path(process['prefix']).resolve()
    if prefix not in directory.resolve().parents:
        return dict(success=False,changed=False,restart_required=False,state='用户目录超出当前前缀，未写入')
    result=inspect_config(directory)
    result.update(success=False,changed=False,restart_required=False)
    if result.get('error'):
        return result
    if result['enabled']:
        result['success']=True
        return result
    path=directory/'log.config'
    if path.is_symlink():
        result['state']='log.config 是软链接，未写入'
        return result
    try:
        original=path.read_bytes() if path.exists() else None
        text=original.decode('utf-8-sig') if original is not None else ''
        lines=text.splitlines(keepends=True)
        output=[]; in_power=False; seen=set(); found=False
        for line in lines:
            header=re.match(r'^\s*\[([^]]+)\]\s*(?:[;#].*)?$',line.strip())
            if header:
                if in_power:
                    output.extend(k+'='+v+'\n' for k,v in POWER.items() if k.lower() not in seen)
                in_power=header[1].lower()=='power'
                if in_power:
                    if found:raise ValueError('存在重复 Power 节，未写入')
                    found=True
            if in_power and not header:
                key=re.match(r'^\s*([^=:#;\s]+)\s*[=:]',line)
                canonical=next((k for k in POWER if key and k.lower()==key[1].lower()),None)
                if canonical:
                    output.append(canonical+'='+POWER[canonical]+'\n');seen.add(canonical.lower());continue
            output.append(line if line.endswith(('\n','\r')) else line+'\n')
        if in_power:
            output.extend(k+'='+v+'\n' for k,v in POWER.items() if k.lower() not in seen)
        if not found:
            output.append('\n[Power]\n');output.extend(k+'='+v+'\n' for k,v in POWER.items())
        directory.mkdir(parents=True,exist_ok=True)
        backup=''
        if original is not None:
            # mkstemp avoids overwriting previous backups; preserve exact original bytes.
            fd,backup=tempfile.mkstemp(prefix='log.config.backup-',dir=directory)
            with os.fdopen(fd,'wb') as f:
                f.write(original);f.flush();os.fsync(f.fileno())
        fd,tmp=tempfile.mkstemp(prefix='.log.config-',dir=directory)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:
                f.write(''.join(output));f.flush();os.fsync(f.fileno())
            os.chmod(tmp,0o600)
            # Preserve concurrent user changes instead of overwriting them.
            if (path.read_bytes() if path.exists() else None)!=original:
                raise ValueError('配置在写入期间发生变化，未覆盖')
            os.replace(tmp,path)
        finally:
            Path(tmp).unlink(missing_ok=True)
        result=inspect_config(directory)
        result.update(success=result['enabled'],changed=True,restart_required=True,backup=backup,
                      state='Power 配置已写入；请完全退出并重新启动炉石')
    except (OSError,ValueError) as exc:
        result.update(success=False,state='配置写入失败：'+str(exc))
    return result


def diagnostic_state(process, config, logs):
    if not process.get('found'):return '游戏进程未发现；无法读取运行时前缀'
    if not process.get('prefix'):return 'Proton 前缀未发现'
    if not config.get('exists'):return 'log.config 不存在；'+config.get('state','')
    if not config.get('enabled'):return 'Power 配置未启用；'+config.get('state','')
    if not logs.get('power'):return 'Power.log 尚未生成' + ('；请完全退出并重启炉石' if config.get('restart_required') else '')
    if not logs['power']['active']:return 'Power.log 已生成但暂未更新'
    return 'Power.log 正常读取' if 'offset' in logs else 'Power.log 已生成，等待读取'
