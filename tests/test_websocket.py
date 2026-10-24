import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from interface.web import build_web_app
from kernel.config import Config
from kernel.daemon import AgentDaemon


class WebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def _client(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        client = TestClient(TestServer(build_web_app(daemon)))
        await client.start_server()
        return daemon, client

    async def test_ping_pong_and_snapshot(self):
        daemon, client = await self._client()
        try:
            ws = await client.ws_connect("/ws")
            await ws.send_str("ping")
            msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
            self.assertEqual(msg["type"], "pong")

            await ws.send_str("snapshot")
            msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
            self.assertEqual(msg["type"], "status")
            self.assertIn("tools", msg["data"])
            await ws.close()
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_log_broadcast_reaches_socket(self):
        daemon, client = await self._client()
        try:
            ws = await client.ws_connect("/ws")
            # allow the subscribe to register before publishing
            await asyncio.sleep(0.05)
            daemon.bus.publish("logs", "ws-test-line-42")
            received = None
            for _ in range(5):
                msg = await asyncio.wait_for(ws.receive(), timeout=5)
                if msg.type == aiohttp_ws_text():
                    payload = json.loads(msg.data)
                    if payload.get("log") == "ws-test-line-42":
                        received = payload
                        break
            self.assertIsNotNone(received, "log line never arrived")
            await ws.close()
        finally:
            await client.close()
            await daemon.memory.close()


    async def test_swarm_events_reach_socket(self):
        daemon, client = await self._client()
        try:
            ws = await client.ws_connect("/ws")
            await asyncio.sleep(0.05)
            daemon.bus.publish("swarm", {"stage": "debate",
                                         "detail": "round 1/2 settled",
                                         "round": 1})
            received = None
            for _ in range(5):
                msg = await asyncio.wait_for(ws.receive(), timeout=5)
                if msg.type == aiohttp_ws_text():
                    payload = json.loads(msg.data)
                    if payload.get("swarm", {}).get("stage") == "debate":
                        received = payload
                        break
            self.assertIsNotNone(received, "swarm event never arrived")
            self.assertEqual(received["swarm"]["round"], 1)
            await ws.close()
        finally:
            await client.close()
            await daemon.memory.close()


def aiohttp_ws_text():
    import aiohttp
    return aiohttp.WSMsgType.TEXT


if __name__ == "__main__":
    unittest.main()
