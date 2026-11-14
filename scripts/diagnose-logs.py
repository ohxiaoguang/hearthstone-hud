#!/usr/bin/env python3
"""Read-only diagnosis using live Hearthstone process environment; no writes."""
import argparse
import os
import json
import sys
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--game-dir',default='/home/deck/Games/battlegame/Hearthstone')
parser.add_argument('--log-path',default='')
a=parser.parse_args()
root=Path(__file__).resolve().parents[1]
modules=root/'py_modules' if (root/'py_modules').is_dir() else root
sys.path.insert(0,str(modules))
from engine.discovery import discover, gamescope_status
from engine.proton import discover_process
from engine.logconfig import inspect_config, diagnostic_state
process=discover_process()
config=inspect_config(process.get('user_dir'))
config.update(success=None,changed=False,restart_required=None,
              auto_config_state='本脚本只读；未发现自动配置记录')
settings=Path(os.environ.get('DECKY_PLUGIN_SETTINGS_DIR',root.parent.parent/'settings'/root.name))
try:
    receipt=json.loads((settings/'power-config-receipt.json').read_text())
    if receipt.get('path')==config.get('path'):
        config.update(success=config['enabled'],restart_required=receipt.get('instance')==process.get('instance'),
                      backup=receipt.get('backup',''),auto_config_state='已找到插件自动配置记录')
except (OSError,ValueError):
    pass
result=discover(process.get('game_dir') or a.game_dir,a.log_path)
result.update(process=process,log_config=config,gamescope=gamescope_status(),
              log_status=diagnostic_state(process,config,result))
print(json.dumps(result,ensure_ascii=False,indent=2))
