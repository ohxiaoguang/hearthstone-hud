"""Bounded, redacted diagnostic text. Never creates an export file."""
import re
from datetime import datetime, timezone

LIMIT=16000


def redact(text):
    text=str(text)
    text=re.sub(r'(?i)(/(?:home|users)/)[^/\s]+',r'\1<user>',text)
    text=re.sub(r'(?i)([A-Z]:\\users\\)[^\\\s]+',r'\1<user>',text)
    text=re.sub(r'\b\d{17}\b','<steam-id>',text)
    text=re.sub(r'(?<!\w)[^\s=\[\]]{1,128}#\d{3,12}', '<player>',text)
    text=re.sub(r'GameAccountId=\[[^]]*\]','GameAccountId=<redacted>',text)
    text=re.sub(r'PlayerName=.*?(?=\n|$)','PlayerName=<redacted>',text)
    text=re.sub(r'''(?i)((?:["']?(?:token|password|secret|authorization|api[_-]?key)["']?)\s*[:=]\s*)(?:"[^"]*"|'[^']*'|(?:Bearer\s+)?[^\s,;]+)''',r'\1<redacted>',text)
    text=re.sub(r'\b[A-Za-z0-9._%+-]{1,128}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}\b','<email>',text)
    return text


def format_diagnostics(data,version,recent=(),renderer_tail=''):
    lines=['Hearthstone HUD Diagnostic'];truncated=False
    def section(name):lines.extend(['','['+name+']'])
    def field(name,value):
        nonlocal truncated
        value=redact(value)
        if len(value)>700:value=value[:700]+' [TRUNCATED]';truncated=True
        lines.append(name+': '+value)
    def stamp(value):
        try:return datetime.fromtimestamp(float(value),timezone.utc).isoformat() if value else 'unknown'
        except (ValueError,TypeError,OverflowError):return 'unknown'
    process=data.get('process',{});logs=data.get('logs',{});cards=data.get('cards',{});tracking=data.get('tracking',{})
    rows=tracking.get('own',[])
    section('Plugin');field('Version',version);field('Status','running' if data.get('running') else 'stopped')
    field('Enabled',data.get('settings',{}).get('enabled',True));field('Background',data.get('background',{}))
    field('Lifecycle',data.get('lifecycle','unknown'))
    section('Game');field('Process','PID '+str(process.get('pid')) if process.get('found') else 'not found')
    field('Prefix',process.get('prefix','unknown'));field('Game Status',data.get('match_status','unknown'))
    field('Players',data.get('identity_status','unknown'));field('Current Turn',tracking.get('turn','unknown'))
    section('Logs');field('Read Status',data.get('log_status','unknown'))
    for key,label in [('power','Power.log'),('decks','Decks.log'),('arena','Arena.log')]:
        item=logs.get(key) or {};field(label,item.get('path','not found'))
        field(label+' Size/Modified',str(item.get('size','unknown'))+' bytes / '+stamp(item.get('mtime')))
    field('Offset/Accepted/Errors',f"{logs.get('offset','unknown')} / {logs.get('accepted',0)} / {data.get('parse_errors',0)}")
    field('Decks Candidates/Errors',f"{logs.get('deck_candidates',0)} / {logs.get('deck_parse_errors',0)}")
    for key in ('power_config','decks_config','arena_config'):
        cfg=data.get(key,{})
        field(key,cfg.get('state','unknown'));field(key+' Restart',cfg.get('restart_required','unknown'))
    section('Deck Tracker');field('Initial Deck',data.get('deck_status','unknown'))
    field('Rows',len(rows));field('Exact Rows',sum(r.get('count_confidence')=='exact' for r in rows))
    field('Lower Bound Rows',sum(r.get('count_confidence')=='lower_bound' for r in rows));field('Unknown Rows',sum(r.get('remaining') is None and not r.get('remaining_lower_bound') for r in rows))
    for key in ('own_added','own_played','opponent_seen','opponent_played'):field(key+' Rows',len(tracking.get(key,[])))
    for key,value in tracking.get('count_evidence',{}).items():field('Evidence '+key,value)
    reasons={}
    for row in rows:
        if row.get('remaining') is None:
            reason=row.get('count_reason','unknown');reasons[reason]=reasons.get(reason,0)+1
    for reason,count in reasons.items():field('Unknown Reason',str(count)+' rows: '+reason)
    arena=data.get('arena',{})
    section('Arena')
    for key in ('deck_id','phase','mode','count','exact','unresolved_choices','conflicts','error'):field(key,arena.get(key,'unknown'))
    field('Candidates',arena.get('source','manual')+' preview only; not counted as picks')
    field('Stage',arena.get('stage','none'))
    field('Association',arena.get('association','logs'))
    field('Recovered History',len(arena.get('history_picks',[])));field('Recovery',arena.get('recovery_source','logs'))
    field('Recovery Note',arena.get('recovery_note',''))
    section('Arena Recovery')
    recovery=arena.get('recovery',{})
    if not recovery:field('Recovery Status','no snapshot taken yet')
    else:
        field('Merge Executed','yes' if recovery.get('merge_executed') else 'no')
        field('Recovery Executed','yes' if recovery.get('executed') else 'no')
        field('Memory Deck Size',recovery.get('deck_parsed','unknown'))
        field('Deck Object','present' if recovery.get('deck_object') else 'missing')
        field('Slot Count',recovery.get('slots','unknown'))
        field('Covered Copies',recovery.get('covered',0))
        deck_reason=str(recovery.get('deck_reason') or 'ok');deck_note=str(recovery.get('deck_note') or '')
        field('Deck Reason',deck_reason+(' ('+deck_note+')' if deck_note else ''))
        field('Snapshot','established' if recovery.get('snapshot') else 'not established')
        if recovery.get('read_start'):
            end=recovery.get('read_settled') or recovery['read_start']
            field('Snapshot Window',f"{recovery['read_start']:.3f} → {end:.3f} ({(end-recovery['read_start'])*1000:.1f} ms)")
        field('Snapshot Size',recovery.get('snapshot_size',0))
        field('Recovered Cards',recovery.get('recovered',0))
        field('Pending Cards',recovery.get('pending',0))
        field('Uncertain Picks',recovery.get('uncertain',0))
        field('Logs Caught Up','yes' if recovery.get('logs_caught_up') else 'no')
        field('Arena Log','found' if recovery.get('arena_log') else 'not found')
        field('Recovery Reason',str(recovery.get('reason',''))+' · '+str(recovery.get('reason_text','')))
    section('Arena Memory')
    for key,value in arena.get('memory',{}).items():field(key,value)
    field('Class Stats Source',arena.get('class_ratings',{}).get('source','unknown'))
    field('Class Stats Snapshot',arena.get('class_ratings',{}).get('captured_at','unknown'))
    field('Ratings',arena.get('ratings',{}).get('source','unknown'))
    field('Snapshot',arena.get('ratings',{}).get('captured_at','unknown'))
    section('TLS')
    field('Image Verification','enabled' if cards.get('image_tls_verify',True) else 'DISABLED: image-only testing mode')
    field('Database Verification','enabled' if cards.get('database_tls_verify',True) else 'DISABLED: database testing mode')
    tls=cards.get('tls',{})
    field('CA Status',tls.get('state','not initialized'));field('Trusted CA Count',tls.get('ca_count','unknown'))
    for source in tls.get('sources',[]):field('CA Source',source)
    for error in tls.get('errors',[]):field('CA Error',error)
    section('Card Database');field('Source',cards.get('source','unknown'));field('Status',cards.get('state','unknown'))
    field('Card Count',cards.get('count',0));field('Last Updated',stamp(cards.get('updated')))
    field('Download',cards.get('download_state','unknown'));field('Last Error',cards.get('error',''))
    storage=data.get('storage',{})
    section('Storage')
    for key in ('runtime','database','images','manual_images'):field(key,storage.get(key,'unknown'))
    field('Uninstall','cache retained; imported source files untouched')
    section('Card Images');counts=cards.get('image_cache',{});batch=cards.get('image_batch',{})
    field('Cached Images',f"manual={counts.get('manual',0)}, automatic={counts.get('automatic',0)}")
    field('Pending Downloads',cards.get('images_pending',0));field('Batch Status',batch.get('status','unknown'))
    field('Total/Success/Failed/Skipped',f"{batch.get('total',0)} / {batch.get('success',0)} / {batch.get('failed',0)} / {batch.get('skipped',0)}")
    field('Last Error',cards.get('image_error',''))
    imported=cards.get('image_import')
    if imported:
        for key in ('found','imported','skipped','format_errors','invalid_ids','other_failures'):
            field('Import '+key,imported.get(key,0))
        for error in imported.get('errors',[])[:5]:field('Import Error',error)
    else:field('Import Result','none')
    section('Renderer');field('Status','running' if data.get('running') else 'stopped');field('Gamescope',data.get('gamescope_status','unknown'))
    diag=data.get('diagnostic',{})
    for key in ('window','external_overlay','mapped','frames','xshape_input_empty'):
        field(key,diag.get(key,'unknown'))
    section('Recent Errors')
    errors=list(recent)+list(cards.get('image_errors',[]))
    for error in errors[-12:]:field('Error',error)
    if len(errors)>12:lines.append('[TRUNCATED: older errors omitted]')
    if data.get('error'):field('Backend',data['error'])
    if renderer_tail:
        field('Renderer Tail',renderer_tail)
    if not errors and not data.get('error') and not renderer_tail:lines.append('No recorded errors')
    text='\n'.join(lines)
    if truncated:text+='\n[TRUNCATED: long fields clipped]'
    if len(text)>LIMIT:text=text[:LIMIT-80]+'\n[TRUNCATED: diagnostic length limit reached]'
    return text
