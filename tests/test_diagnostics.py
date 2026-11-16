from pathlib import Path
import tempfile
import unittest
from engine.diagnostics import format_diagnostics,redact,LIMIT

class DiagnosticTests(unittest.TestCase):
    def test_redaction(self):
        text='''/home/private-user/Logs /Users/private-user/file C:\\Users\\PrivateName\\AppData
PlayerName=RealPlayer#1234
GameAccountId=[hi=123 lo=456] Steam 76561198012345678
{"token": "sensitive value", "password":"secret-word"}
Authorization: Bearer bearer-secret
Email private@example.com api_key=api-secret'''
        result=redact(text)
        for secret in ['private-user','PrivateName','RealPlayer','hi=123','76561198012345678','sensitive value','secret-word','bearer-secret','private@example.com','api-secret']:
            self.assertNotIn(secret,result)
    def test_structured_bounded_truncation_and_no_export(self):
        data=dict(running=True,match_status='对局已识别',identity_status='双方身份已识别',deck_status='完整卡组未知',
                  cards=dict(count=0,state='不可用',image_error='x'*10000,image_batch=dict(total=2,success=1,failed=1,skipped=0)),
                  logs=dict(accepted=1007),tracking=dict(turn=3,own=[dict(remaining=2,count_confidence='exact'),dict(remaining=None)]))
        with tempfile.TemporaryDirectory() as folder:
            before=list(Path(folder).rglob('*'))
            report=format_diagnostics(data,'0.2.3',['error '+str(i) for i in range(50)],'r'*10000)
            self.assertEqual(before,list(Path(folder).rglob('*')))
        for section in ['[Plugin]','[Game]','[Logs]','[Deck Tracker]','[Card Database]','[Card Images]','[Renderer]','[Recent Errors]']:
            self.assertIn(section,report)
        self.assertIn('TRUNCATED',report);self.assertLessEqual(len(report),LIMIT);self.assertIn('1007',report)
        self.assertIn('Exact Rows: 1',report);self.assertIn('Unknown Rows: 1',report)

    def test_hover_pipeline_stages_are_in_copied_diagnostics(self):
        data=dict(diagnostic=dict(hover=dict(stage='no_hit',card_regions=30,
                  pointer=dict(query_ok=True,client_size=[2560,1440],display_size=[1280,720]))),
                  full_card_preview=dict(stage='download_failed',error='HTTP 404',id='CARD_A'))
        report=format_diagnostics(data,'test')
        for text in ('[Hover Preview]','Renderer stage: no_hit','Renderer card_regions: 30',
                     'Downloader stage: download_failed','HTTP 404'):
            self.assertIn(text,report)

    def test_registration_details_survive_copying_after_match_ends(self):
        registration=dict(stage='no_card_regions',registration_state='no_cards',registration_frame=200,
            card_regions=0,registered_ids=[],
            render_context=dict(tracking_status='waiting',hud_visible=True),
            panels=dict(remaining=dict(available=0,registered=0)),
            last_nonempty_registration=dict(frame=150,card_regions=3,ids=['CORE_CS2_029','HERO_08']),
            last_hit=dict(frame=151,id='HERO_08',source='arena-offer'))
        report=format_diagnostics(dict(diagnostic=dict(hover=registration)),'test')
        for text in ('Renderer registration_state: no_cards','Renderer registration_frame: 200',
                     'CORE_CS2_029','HERO_08','Renderer last_hit:',"'frame': 151",'arena-offer'):
            self.assertIn(text,report)
        self.assertNotIn('TRUNCATED',report)

    def test_game_and_renderer_displays_and_hover_history_are_reported(self):
        report=format_diagnostics(dict(process=dict(environment=dict(DISPLAY=':1')),
            diagnostic=dict(display=':0',hover=dict(pointer_history=dict(position_changes_with_cards=0),
            last_request=dict(frame=100,id='CORE_CS2_029')))),'test')
        for text in ('X11 Display: :1','display: :0','position_changes_with_cards','Renderer last_request:','CORE_CS2_029'):
            self.assertIn(text,report)
