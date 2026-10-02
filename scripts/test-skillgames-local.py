"""Network harness safety and real-HTTP smoke, separate from fixture UI tests."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'scripts' / 'run-skillgames-local.py'

class LocalHarnessTests(unittest.TestCase):
    def test_explicit_local_only_harness_is_required(self):
        self.assertTrue(RUNNER.exists(), 'Missing real-HTTP local skillgame runner; fixture preview is not integration')
        rejected = subprocess.run([sys.executable, str(RUNNER)],capture_output=True,text=True)
        self.assertNotEqual(rejected.returncode,0)
        self.assertIn('--allow-local-demo',rejected.stderr)

    def test_no_production_database_or_public_bind_arguments(self):
        self.assertTrue(RUNNER.exists(), 'Missing local integration harness')
        help_result = subprocess.run([sys.executable,str(RUNNER),'--help'],capture_output=True,text=True)
        self.assertEqual(help_result.returncode,0)
        self.assertNotIn('--host',help_result.stdout)
        self.assertNotIn('--db',help_result.stdout)
        self.assertIn('--port',help_result.stdout)

class LiveLocalHarnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_signed_http_startup_and_safety(self):
        import httpx
        spec = importlib.util.spec_from_file_location('skillgames_local_runner', RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app = module.create_local_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',5000)),base_url='http://127.0.0.1:4180') as client:
                identity = await client.get('/local-identity?player=alice')
                self.assertEqual(identity.status_code,200,identity.text)
                assert identity.json()['userId'].startswith('U'), 'Local helper must exercise opaque Twitch identity, not bypass new-user onboarding'
                headers = {'X-Twitch-JWT':identity.json()['token']}
                self.assertEqual((await client.get('/api/skillgames/state',headers=headers)).status_code,401)
                resolved = await client.post('/api/user/resolve-twitch-token',json={'token':identity.json()['token'],'opaque_id':identity.json()['userId']})
                self.assertEqual(resolved.status_code,200,resolved.text)
                self.assertEqual(resolved.json()['login'],'alice')
                state = await client.get('/api/skillgames/state',headers=headers)
                self.assertEqual(state.status_code,200,state.text)
                self.assertEqual(len(state.json()['catalog']),2)
                denied = await client.get('/local-identity',headers={'Origin':'https://evil.example'})
                self.assertEqual(denied.status_code,403)
                rebind = await client.get('/local-identity',headers={'Host':'evil.example'})
                self.assertEqual(rebind.status_code,403)
                missing = await client.get('/api/skillgames/state')
                self.assertEqual(missing.status_code,401)

if __name__ == '__main__': unittest.main()
