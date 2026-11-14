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
