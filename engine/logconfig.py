"""Atomic, backed-up section-scoped edits in the currently discovered live prefix."""
import configparser
import os
from pathlib import Path
import re
import tempfile
from . import i18n

POWER = dict(LogLevel='1',FilePrinting='True',ConsolePrinting='False',ScreenPrinting='False',Verbose='True')
DECKS = dict(POWER,Verbose='False')
ARENA = dict(POWER)
SECTIONS = {'Power':POWER,'Decks':DECKS,'Arena':ARENA}


def inspect_config(user_dir, section_name='Power'):
    required = SECTIONS[section_name]
    if not user_dir:
        return dict(path='',exists=False,enabled=False,state=i18n.t('log.no_user_dir'))
    path = Path(user_dir)/'log.config'
    result = dict(path=str(path),exists=path.exists(),enabled=False,state=i18n.t('log.no_config'))
    if not result['exists']:
        return result
    try:
        parser=configparser.ConfigParser(interpolation=None)
        parser.read_string(path.read_text(encoding='utf-8-sig'))
        section=next((s for s in parser.sections() if s.lower()==section_name.lower()),None)
        result['enabled']=bool(section and all(parser.get(section,k,fallback='').strip().lower()==v.lower() for k,v in required.items()))
        result['state']=i18n.t('log.enabled' if result['enabled'] else 'log.disabled',section=section_name)
    except (OSError,ValueError,configparser.Error) as exc:
        result['state']=i18n.t('log.unparsable',error=str(exc))
        result['error']=str(exc)
    return result


def ensure_power(process):
    return ensure_section(process, 'Power')


def ensure_decks(process):
    return ensure_section(process, 'Decks')


def ensure_arena(process):
    return ensure_section(process, 'Arena')


def ensure_section(process, section_name):
    if section_name not in SECTIONS:
        raise ValueError(i18n.t('log.unsupported_section'))
    required = SECTIONS[section_name]
    if not process.get('found') or not process.get('prefix') or not process.get('user_dir'):
        return dict(path='',exists=False,enabled=False,success=False,changed=False,restart_required=False,
                    state=process.get('error') or i18n.t('log.prefix_missing'))
    directory=Path(process['user_dir'])
    # Refuse paths escaping the discovered prefix (including existing symlinks).
    prefix=Path(process['prefix']).resolve()
    if prefix not in directory.resolve().parents:
        return dict(success=False,changed=False,restart_required=False,state=i18n.t('log.outside_prefix'))
    result=inspect_config(directory,section_name)
    result.update(success=False,changed=False,restart_required=False)
    if result.get('error'):
        return result
    if result['enabled']:
        result['success']=True
        return result
    path=directory/'log.config'
    if path.is_symlink():
        result['state']=i18n.t('log.symlink')
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
                    output.extend(k+'='+v+'\n' for k,v in required.items() if k.lower() not in seen)
                in_power=header[1].lower()==section_name.lower()
                if in_power:
                    if found:raise ValueError(i18n.t('log.duplicate',section=section_name))
                    found=True
            if in_power and not header:
                key=re.match(r'^\s*([^=:#;\s]+)\s*[=:]',line)
                canonical=next((k for k in required if key and k.lower()==key[1].lower()),None)
                if canonical:
                    output.append(canonical+'='+required[canonical]+'\n');seen.add(canonical.lower());continue
            output.append(line if line.endswith(('\n','\r')) else line+'\n')
        if in_power:
            output.extend(k+'='+v+'\n' for k,v in required.items() if k.lower() not in seen)
        if not found:
            output.append('\n['+section_name+']\n');output.extend(k+'='+v+'\n' for k,v in required.items())
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
                raise ValueError(i18n.t('log.changed_during_write'))
            os.replace(tmp,path)
        finally:
            Path(tmp).unlink(missing_ok=True)
        result=inspect_config(directory,section_name)
        result.update(success=result['enabled'],changed=True,restart_required=True,backup=backup,
                      state=i18n.t('log.written',section=section_name))
    except (OSError,ValueError) as exc:
        result.update(success=False,state=i18n.t('log.write_failed',error=str(exc)))
    return result


def diagnostic_state(process, config, logs):
    if not process.get('found'):return i18n.t('log.process_missing')
    if not process.get('prefix'):return i18n.t('log.prefix_missing')
    if not config.get('exists'):return i18n.t('log.config_missing',state=config.get('state',''))
    if not config.get('enabled'):return i18n.t('log.power_disabled',state=config.get('state',''))
    if not logs.get('power'):
        return i18n.t('log.power_missing',restart=i18n.t('log.restart_hint') if config.get('restart_required') else '')
    if logs.get('parse_failed') or str(logs.get('read_state','')).startswith(i18n.t('log.read_failed',error='')):
        return logs['read_state']
    if not logs['power']['active']:return i18n.t('log.power_idle')
    return i18n.t('log.power_ok') if 'offset' in logs else i18n.t('log.power_waiting')
