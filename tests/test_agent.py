import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from outbound_agent.engine import AgentEngine, load_tasks
from outbound_agent.evaluation import EvaluationRunner
from outbound_agent.llm import LLMClient
from outbound_agent.models import Session


ROOT = Path(__file__).resolve().parents[1]


class AgentEngineTest(unittest.TestCase):
    def setUp(self):
        self.tasks = load_tasks(ROOT / "data" / "tasks.json")
        self.engine = AgentEngine(self.tasks)

    def test_rider_start_and_requirement(self):
        session = Session(task_id="rider_flying_leg", variables={"rider_name": "李师傅"})
        opening = self.engine.start(session)
        self.assertIn("李师傅", opening.content)

        reply = self.engine.message(session, "要跑多少单")
        self.assertIn("单日", reply.content)
        self.assertLessEqual(len(reply.content), 30)

    def test_rider_identity_question_does_not_end_as_wrong_number(self):
        session = Session(task_id="rider_flying_leg", variables={"rider_name": "李师傅"})
        self.engine.start(session)

        reply = self.engine.message(session, "你是谁")

        self.assertFalse(session.ended)
        self.assertIn("站长", reply.content)
        self.assertNotIn("核对下号码", reply.content)

    def test_rider_wrong_number_still_ends(self):
        session = Session(task_id="rider_flying_leg", variables={"rider_name": "李师傅"})
        self.engine.start(session)

        reply = self.engine.message(session, "你打错了，我不是本人")

        self.assertTrue(session.ended)
        self.assertIn("核对下号码", reply.content)

    def test_rider_unable_twice_ends(self):
        session = Session(task_id="rider_flying_leg", variables={})
        self.engine.start(session)
        self.engine.message(session, "今天跑不了")
        reply = self.engine.message(session, "确实不跑")
        self.assertTrue(session.ended)
        self.assertIn("理解", reply.content)

    def test_course_busy_and_driving(self):
        session = Session(task_id="course_live_upgrade", variables={})
        self.engine.start(session)
        busy = self.engine.message(session, "我现在很忙")
        self.assertEqual(busy.content, "就1分钟，保证简短")

        driving = self.engine.message(session, "我在开车")
        self.assertTrue(session.ended)
        self.assertEqual(driving.content, "那我稍后再打")

    def test_course_no_coupon_promise(self):
        session = Session(task_id="course_live_upgrade", variables={})
        self.engine.start(session)
        reply = self.engine.message(session, "能给优惠券吗")
        self.assertIn("不能承诺", reply.content)
        self.assertNotIn("好的", reply.content)

    def test_evaluation_runner_outputs_quantified_report(self):
        runner = EvaluationRunner(self.engine, self.tasks)

        report = runner.run(task_id="rider_flying_leg", mode="rule")

        self.assertIn("summary", report)
        self.assertGreater(report["summary"]["scenario_count"], 0)
        self.assertGreater(report["summary"]["check_count"], 0)
        self.assertIsInstance(report["summary"]["score"], float)
        task_report = report["task_reports"][0]
        self.assertTrue(task_report["dimensions"])
        self.assertTrue(task_report["scenarios"][0]["evidence"])

    def test_evaluation_runner_accepts_enterprise_settings(self):
        runner = EvaluationRunner(self.engine, self.tasks)

        report = runner.run(
            task_id="rider_flying_leg",
            mode="rule",
            settings={
                "scope": "quick",
                "weights": {"任务覆盖": 2.0, "可靠性": 1.5},
                "thresholds": {"excellent": 95, "pass": 80, "risk": 60},
            },
        )

        self.assertEqual(report["settings"]["scope"], "quick")
        self.assertEqual(report["settings"]["weights"]["任务覆盖"], 2.0)
        self.assertEqual(report["summary"]["scenario_count"], 2)
        self.assertIn("raw_score", report["summary"])

    def test_evaluation_runner_outputs_comparison_report(self):
        runner = EvaluationRunner(self.engine, self.tasks)

        report = runner.compare(
            task_id="rider_flying_leg",
            modes=["rule", "rule"],
            settings={"scope": "quick"},
        )

        self.assertEqual(len(report["comparisons"]), 2)
        self.assertEqual(report["baseline_mode"], "rule")
        self.assertIn("reports", report)

    def test_llm_config_is_masked_in_session_dict(self):
        session = Session(
            task_id="course_live_upgrade",
            variables={},
            mode="llm",
            llm_config={
                "base_url": "https://example.test/v1",
                "model": "demo-model",
                "api_key": "secret-key",
            },
        )
        data = session.to_dict()
        self.assertTrue(data["llm"]["configured"])
        self.assertTrue(data["llm"]["has_api_key"])
        self.assertEqual(data["llm"]["model"], "demo-model")
        self.assertNotIn("secret-key", str(data))

    def test_llm_endpoint_accepts_base_url_or_full_url(self):
        client = LLMClient()
        self.assertEqual(
            client._chat_endpoint("https://example.test/v1"),
            "https://example.test/v1/chat/completions",
        )
        self.assertEqual(
            client._chat_endpoint("https://example.test/v1/chat/completions"),
            "https://example.test/v1/chat/completions",
        )

    def test_llm_client_reads_global_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "llm.json"
            config_path.write_text(
                json.dumps(
                    {
                        "base_url": "https://example.test/v1",
                        "model": "file-model",
                        "api_key": "file-key",
                    }
                ),
                encoding="utf-8",
            )

            client = LLMClient(config_path=str(config_path))
            api_key, model, endpoint = client._resolve_values({})
            status = client.config_status()

            self.assertEqual(api_key, "file-key")
            self.assertEqual(model, "file-model")
            self.assertEqual(endpoint, "https://example.test/v1/chat/completions")
            self.assertTrue(status["configured"])
            self.assertTrue(status["has_api_key"])

    def test_llm_mode_uses_model_reply(self):
        class FakeLLM:
            def generate_voice_reply(self, task, session, user_text, plan):
                if plan.get("exact_text"):
                    return plan["exact_text"]
                return "model reply"

        session = Session(task_id="course_live_upgrade", variables={}, mode="llm")
        self.engine.llm = FakeLLM()
        self.engine.start(session)
        reply = self.engine.message(session, "hello")

        self.assertEqual(reply.content, "model reply")
        self.assertEqual(session.meta["last_reply_source"], "llm")

    def test_llm_mode_does_not_silently_fallback(self):
        class FailingLLM:
            def generate_voice_reply(self, task, session, user_text, plan):
                raise RuntimeError("boom")

        session = Session(task_id="course_live_upgrade", variables={}, mode="llm")
        self.engine.llm = FailingLLM()
        self.engine.start(session)
        reply = self.engine.message(session, "hello")

        self.assertIn("boom", reply.content)
        self.assertEqual(session.meta["last_reply_source"], "llm_error")

    def test_llm_mode_calls_model_for_opening_and_business_plan(self):
        calls = []

        class RecordingLLM:
            def generate_voice_reply(self, task, session, user_text, plan):
                calls.append(plan)
                return plan.get("exact_text") or "我来按计划说"

        session = Session(task_id="course_live_upgrade", variables={}, mode="llm")
        self.engine.llm = RecordingLLM()

        opening = self.engine.start(session)
        reply = self.engine.message(session, "我是负责人")

        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(calls[0]["intent"], "开场白")
        self.assertEqual(calls[1]["intent"], "负责人确认后传达升级概览")
        self.assertIn("您好", opening.content)
        self.assertEqual(reply.content, "我来按计划说")

    def test_llm_mode_calls_model_but_guards_hangup_phrase(self):
        calls = []

        class BadLLM:
            def generate_voice_reply(self, task, session, user_text, plan):
                calls.append(plan)
                return "我多解释几句，先不要挂"

        session = Session(task_id="course_live_upgrade", variables={}, mode="llm")
        self.engine.llm = BadLLM()
        self.engine.start(session)
        reply = self.engine.message(session, "我在开车")

        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(calls[-1]["intent"], "商家正在开车，礼貌挂断")
        self.assertEqual(reply.content, "那我稍后再打")
        self.assertTrue(session.ended)

    def test_llm_messages_do_not_duplicate_latest_user_text(self):
        client = LLMClient()
        task = self.tasks["course_live_upgrade"]
        session = Session(task_id="course_live_upgrade", variables={})
        session.add("assistant", "opening")
        session.add("user", "hello")

        messages = client._messages(task, session, "hello")
        user_messages = [
            item
            for item in messages
            if item["role"] == "user" and item["content"] == "hello"
        ]
        self.assertEqual(len(user_messages), 1)

    def test_llm_client_posts_to_chat_completions(self):
        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                captured["path"] = self.path
                captured["authorization"] = self.headers.get("Authorization")
                captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
                raw = json.dumps(
                    {"choices": [{"message": {"content": "server reply"}}]},
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, fmt, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            client = LLMClient()
            task = self.tasks["course_live_upgrade"]
            session = Session(
                task_id="course_live_upgrade",
                variables={},
                llm_config={
                    "base_url": f"http://127.0.0.1:{port}/v1",
                    "model": "demo-model",
                    "api_key": "test-key",
                },
            )
            session.add("user", "hello")

            reply = client.reply(task, session, "hello")

            self.assertEqual(reply, "server reply")
            self.assertEqual(captured["path"], "/v1/chat/completions")
            self.assertEqual(captured["authorization"], "Bearer test-key")
            self.assertEqual(captured["body"]["model"], "demo-model")
        finally:
            server.shutdown()
            server.server_close()

    def test_llm_client_posts_planned_prompt(self):
        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
                raw = json.dumps(
                    {"choices": [{"message": {"content": "planned reply"}}]},
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, fmt, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            client = LLMClient()
            task = self.tasks["course_live_upgrade"]
            session = Session(
                task_id="course_live_upgrade",
                variables={},
                llm_config={
                    "base_url": f"http://127.0.0.1:{port}/v1",
                    "model": "demo-model",
                    "api_key": "test-key",
                },
            )
            plan = {
                "intent": "测试计划",
                "required_points": ["必须覆盖"],
                "max_chars": 20,
                "exact_text": "",
            }

            reply = client.reply_from_plan(task, session, "hello", plan)

            self.assertEqual(reply, "planned reply")
            text = json.dumps(captured["body"]["messages"], ensure_ascii=False)
            self.assertIn("Next Reply Plan", text)
            self.assertIn("必须覆盖", text)
            self.assertIn("不能改流程", text)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
