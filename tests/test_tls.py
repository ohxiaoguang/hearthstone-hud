from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch
from engine import tls

class TrustTests(unittest.TestCase):
    def test_bundled_ca_restores_empty_embedded_python_store(self):
        empty=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.assertEqual(empty.cert_store_stats()['x509_ca'],0)
        with patch.object(tls.ssl,'create_default_context',return_value=empty),patch.object(tls,'SYSTEM_CA_FILES',()):
            context,info=tls.build_context()
        self.assertGreater(info['ca_count'],100)
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED);self.assertTrue(context.check_hostname)
        self.assertIn(str(tls.BUNDLE),info['sources'])
    def test_missing_ca_does_not_disable_verification(self):
        empty=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(tls.ssl,'create_default_context',return_value=empty),patch.object(tls,'SYSTEM_CA_FILES',()),patch.object(tls,'BUNDLE',Path(folder)/'missing.pem'):
                with self.assertRaises(ssl.SSLError):tls.build_context()
        self.assertEqual(empty.verify_mode,ssl.CERT_REQUIRED);self.assertTrue(empty.check_hostname)
    def test_image_testing_switch_does_not_disable_database_tls(self):
        from unittest.mock import MagicMock
        from engine.cards import Cards,fetch,DATA_URL
        from image_support import tile_png
        response=MagicMock();response.__enter__.return_value.read.return_value=tile_png()
        with tempfile.TemporaryDirectory() as folder:
            cards=Cards(folder);cards.image_verify_tls=False
            with patch('engine.cards.urllib.request.urlopen',return_value=response) as request:
                cards.download_image('CARD_A')
                image_context=request.call_args.kwargs['context']
                self.assertEqual(image_context.verify_mode,ssl.CERT_NONE)
                self.assertFalse(image_context.check_hostname)
                fetch(DATA_URL,1024*1024)
                data_context=request.call_args.kwargs['context']
                self.assertEqual(data_context.verify_mode,ssl.CERT_REQUIRED)
                self.assertTrue(data_context.check_hostname)
