#!/usr/bin/env python3
"""Read-only SteamOS diagnosis; standard Python only, no configuration writes."""
import argparse
import configparser
import importlib.util
import json
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--game-dir',default='/home/deck/Games/battlegame/Hearthstone')
parser.add_argument('--log-path',default='')
parser.add_argument('--prefix',default='/home/deck/.local/share/Steam/steamapps/compatdata/3443960088/pfx')
a=parser.parse_args()
root=Path(__file__).resolve().parents[1]
module=next((p for p in [root/'py_modules/engine/discovery.py',root/'engine/discovery.py'] if p.exists()),None)
if module is None:raise SystemExit('请将脚本放在已安装插件的 scripts/ 下运行')
spec=importlib.util.spec_from_file_location('discovery',module);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
result=m.discover(a.game_dir,a.log_path)
path=Path(a.prefix)/'drive_c/users/steamuser/AppData/Local/Blizzard/Hearthstone/log.config'
config=configparser.ConfigParser(strict=False)
try:
    with path.open() as f:config.read_file(f)
    result['log_config']={'path':str(path),'sections':{s:dict(config[s]) for s in ['Power','Decks'] if config.has_section(s)}}
except (OSError,configparser.Error) as exc:result['log_config']={'path':str(path),'error':str(exc)}
result['gamescope']=m.gamescope_status()
print(json.dumps(result,ensure_ascii=False,indent=2))
