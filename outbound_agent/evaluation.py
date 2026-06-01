from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from outbound_agent.engine import AgentEngine
from outbound_agent.models import Session, Task


@dataclass
class UserTurn:
    user: str
    intent: str = ""
    contains_all: list[str] = field(default_factory=list)
    contains_any: list[str] = field(default_factory=list)
    not_contains: list[str] = field(default_factory=list)
    should_end: bool | None = None
    note: str = ""


@dataclass
class EvaluationScenario:
    id: str
    title: str
    description: str
    turns: list[UserTurn]


class EvaluationRunner:
    """Automatic instruction-following evaluator with deterministic user simulation."""

    def __init__(self, engine: AgentEngine, tasks: dict[str, Task]) -> None:
        self.engine = engine
        self.tasks = tasks

    def run(
        self,
        task_id: str | None = None,
        mode: str = "rule",
        variables: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        selected_tasks = [self.tasks[task_id]] if task_id else list(self.tasks.values())
        task_reports = [
            self._run_task(task, mode, variables or {}) for task in selected_tasks
        ]
        total_checks = sum(report["check_count"] for report in task_reports)
        passed_checks = sum(report["passed_count"] for report in task_reports)
        score = self._score(passed_checks, total_checks)
        return {
            "generated_at": time.time(),
            "mode": mode,
            "summary": {
                "score": score,
                "task_count": len(task_reports),
                "scenario_count": sum(len(report["scenarios"]) for report in task_reports),
                "check_count": total_checks,
                "passed_count": passed_checks,
                "conclusion": self._conclusion(score),
            },
            "task_reports": task_reports,
        }

    def scenarios_for(self, task: Task) -> list[EvaluationScenario]:
        if task.id == "rider_flying_leg":
            return [
                EvaluationScenario(
                    id="rider_happy_path",
                    title="正常确认配送",
                    description="用户确认本人并愿意配送，检查合同生效和上线提醒。",
                    turns=[
                        UserTurn(
                            "我是本人",
                            intent="告知合同生效并确认能否开跑",
                            contains_all=["合同"],
                            should_end=False,
                        ),
                        UserTurn(
                            "今天可以跑",
                            intent="鼓励开始配送",
                            contains_any=["上线", "安全"],
                            should_end=False,
                        ),
                    ],
                ),
                EvaluationScenario(
                    id="rider_identity_and_requirement",
                    title="身份询问与单量追问",
                    description="用户询问坐席身份，再追问需要完成多少单。",
                    turns=[
                        UserTurn(
                            "你是谁",
                            intent="说明坐席身份",
                            contains_all=["站长"],
                            not_contains=["核对下号码"],
                            should_end=False,
                        ),
                        UserTurn(
                            "要跑多少单",
                            intent="解释单量要求",
                            contains_all=["单日", "多日"],
                            should_end=False,
                        ),
                    ],
                ),
                EvaluationScenario(
                    id="rider_unable_to_deliver",
                    title="拒绝配送挽留",
                    description="用户先表示跑不了，再坚持不跑，检查挽留和结束策略。",
                    turns=[
                        UserTurn(
                            "今天跑不了",
                            intent="挽留不想配送的骑手",
                            contains_any=["名额", "尽量"],
                            should_end=False,
                        ),
                        UserTurn(
                            "确实不跑",
                            intent="骑手坚持无法配送，安慰后结束",
                            contains_all=["理解"],
                            should_end=True,
                        ),
                    ],
                ),
                EvaluationScenario(
                    id="rider_rules_faq",
                    title="资格与退出规则",
                    description="用户追问为什么是自己以及如何退出。",
                    turns=[
                        UserTurn(
                            "为什么是我",
                            intent="解释飞毛腿资格规则",
                            contains_all=["排名"],
                            should_end=False,
                        ),
                        UserTurn(
                            "怎么退出",
                            intent="解释退出规则",
                            contains_any=["退出", "取消"],
                            should_end=False,
                        ),
                    ],
                ),
                EvaluationScenario(
                    id="rider_wrong_number",
                    title="错号处理",
                    description="用户明确表示不是本人，检查是否礼貌结束。",
                    turns=[
                        UserTurn(
                            "你打错了，我不是本人",
                            intent="号码不匹配，结束通话",
                            contains_all=["核对下号码"],
                            should_end=True,
                        )
                    ],
                ),
            ]
        if task.id == "course_live_upgrade":
            return [
                EvaluationScenario(
                    id="course_upgrade_awareness",
                    title="升级信息确认",
                    description="负责人确认身份后，对临时低延迟线路表示不清楚。",
                    turns=[
                        UserTurn(
                            "我是负责人",
                            intent="负责人确认后传达升级概览",
                            contains_all=["低延迟"],
                            should_end=False,
                        ),
                        UserTurn(
                            "不知道",
                            intent="确认是否知情",
                            contains_any=["之前", "后台"],
                            should_end=False,
                        ),
                        UserTurn(
                            "不清楚",
                            intent="解释此前未开放原因",
                            contains_any=["前端", "临时"],
                            should_end=False,
                        ),
                    ],
                ),
                EvaluationScenario(
                    id="course_price_and_difference",
                    title="费用与差异追问",
                    description="用户询问价格和两类直播的区别。",
                    turns=[
                        UserTurn(
                            "价格有变化吗",
                            intent="解释价格",
                            contains_all=["标准", "低延迟"],
                            should_end=False,
                        ),
                        UserTurn(
                            "区别是什么",
                            intent="解释直播区别",
                            contains_any=["5到10秒", "1到2秒"],
                            should_end=False,
                        ),
                    ],
                ),
                EvaluationScenario(
                    id="course_busy",
                    title="忙碌挽留",
                    description="用户表示没时间，检查是否按要求极短挽留。",
                    turns=[
                        UserTurn(
                            "我现在很忙",
                            intent="老板忙，按要求简短挽留",
                            contains_all=["1分钟"],
                            should_end=False,
                        )
                    ],
                ),
                EvaluationScenario(
                    id="course_driving",
                    title="开车挂断",
                    description="用户正在开车，检查是否礼貌挂断。",
                    turns=[
                        UserTurn(
                            "我在开车",
                            intent="商家正在开车，礼貌挂断",
                            contains_all=["稍后再打"],
                            should_end=True,
                        )
                    ],
                ),
                EvaluationScenario(
                    id="course_third_party_guide",
                    title="第三方入口不可见",
                    description="用户走到发布方式确认后，反馈第三方系统看不到入口。",
                    turns=[
                        UserTurn("我是负责人", intent="负责人确认后传达升级概览"),
                        UserTurn("知道", intent="确认是否知情"),
                        UserTurn("继续", intent="传达发布页升级"),
                        UserTurn("继续", intent="说明标准直播"),
                        UserTurn("继续", intent="说明低延迟直播"),
                        UserTurn("继续", intent="询问发布方式"),
                        UserTurn(
                            "第三方里看不到",
                            intent="第三方系统未显示，准备引导开通",
                            contains_any=["开通", "慢慢来"],
                            should_end=False,
                        ),
                        UserTurn(
                            "下一步",
                            intent="慢速引导第1步",
                            contains_all=["我的"],
                            should_end=False,
                        ),
                    ],
                ),
            ]
        return [
            EvaluationScenario(
                id=f"{task.id}_basic",
                title="基础覆盖",
                description="使用任务快捷回复进行基础模拟。",
                turns=[UserTurn(item) for item in task.quick_replies[:4]],
            )
        ]

    def _run_task(
        self,
        task: Task,
        mode: str,
        variables: dict[str, str],
    ) -> dict[str, Any]:
        scenarios = self.scenarios_for(task)
        scenario_reports = [
            self._run_scenario(task, scenario, mode, variables) for scenario in scenarios
        ]
        checks = [
            check
            for scenario_report in scenario_reports
            for check in scenario_report["checks"]
        ]
        passed = sum(1 for check in checks if check["passed"])
        dimensions = self._dimensions(checks)
        score = self._score(passed, len(checks))
        return {
            "task_id": task.id,
            "task_title": task.title,
            "score": score,
            "check_count": len(checks),
            "passed_count": passed,
            "dimensions": dimensions,
            "scenarios": scenario_reports,
            "conclusion": self._conclusion(score),
        }

    def _run_scenario(
        self,
        task: Task,
        scenario: EvaluationScenario,
        mode: str,
        variables: dict[str, str],
    ) -> dict[str, Any]:
        session = Session(
            task_id=task.id,
            variables={**task.defaults(), **variables},
            mode=mode,
        )
        evidence: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []

        opening = self.engine.start(session)
        evidence.append(
            {
                "turn": 0,
                "user": "(系统开场)",
                "assistant": opening.content,
                "intent": session.meta.get("reply_plan", {}).get("intent", "开场白"),
                "status": session.status,
            }
        )
        checks.append(
            self._check(
                "开场白生成",
                "任务启动",
                bool(opening.content.strip()),
                opening.content,
            )
        )

        for index, turn in enumerate(scenario.turns, start=1):
            if session.ended:
                checks.append(
                    self._check(
                        f"第{index}轮可继续对话",
                        "流程控制",
                        False,
                        "会话已提前结束，无法继续执行模拟用户脚本。",
                    )
                )
                break
            reply = self.engine.message(session, turn.user)
            plan = dict(session.meta.get("reply_plan") or {})
            turn_checks = self._evaluate_turn(task, turn, reply.content, session, plan)
            checks.extend(turn_checks)
            evidence.append(
                {
                    "turn": index,
                    "user": turn.user,
                    "assistant": reply.content,
                    "intent": plan.get("intent", ""),
                    "status": plan.get("status", session.status),
                    "expected_intent": turn.intent,
                    "passed": all(item["passed"] for item in turn_checks),
                    "checks": turn_checks,
                }
            )

        passed = sum(1 for check in checks if check["passed"])
        return {
            "id": scenario.id,
            "title": scenario.title,
            "description": scenario.description,
            "score": self._score(passed, len(checks)),
            "check_count": len(checks),
            "passed_count": passed,
            "checks": checks,
            "evidence": evidence,
        }

    def _evaluate_turn(
        self,
        task: Task,
        turn: UserTurn,
        reply: str,
        session: Session,
        plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        if turn.intent:
            actual = str(plan.get("intent") or "")
            checks.append(
                self._check(
                    f"意图命中：{turn.intent}",
                    "任务覆盖",
                    turn.intent in actual or actual in turn.intent,
                    f"实际意图：{actual or '无'}",
                )
            )
        if turn.contains_all:
            missing = [item for item in turn.contains_all if item not in reply]
            checks.append(
                self._check(
                    "必须信息覆盖",
                    "任务覆盖",
                    not missing,
                    f"缺失关键词：{missing}；回复：{reply}",
                )
            )
        if turn.contains_any:
            checks.append(
                self._check(
                    "关键信息命中",
                    "任务覆盖",
                    any(item in reply for item in turn.contains_any),
                    f"候选关键词：{turn.contains_any}；回复：{reply}",
                )
            )
        if turn.not_contains:
            present = [item for item in turn.not_contains if item in reply]
            checks.append(
                self._check(
                    "禁止信息未出现",
                    "约束遵守",
                    not present,
                    f"出现禁止关键词：{present}；回复：{reply}",
                )
            )
        if turn.should_end is not None:
            checks.append(
                self._check(
                    "结束状态正确",
                    "流程控制",
                    session.ended is turn.should_end,
                    f"期望 ended={turn.should_end}，实际 ended={session.ended}",
                )
            )

        limit = self._reply_limit(task)
        checks.append(
            self._check(
                "回复长度约束",
                "约束遵守",
                len(reply) <= limit + 8,
                f"长度 {len(reply)}，限制约 {limit} 字；回复：{reply}",
            )
        )

        if task.id == "course_live_upgrade":
            banned = ["好的", "哈哈", "嘿嘿", "嘻嘻"]
            present = [item for item in banned if item in reply]
            checks.append(
                self._check(
                    "课程任务语气词约束",
                    "约束遵守",
                    not present,
                    f"出现禁止语气词：{present}",
                )
            )

        llm_error = (
            session.meta.get("last_reply_source") == "llm_error"
            or reply.startswith("大模型调用失败")
        )
        checks.append(
            self._check(
                "回复生成可靠性",
                "可靠性",
                not llm_error,
                str(session.meta.get("llm_error") or "未发现模型调用错误"),
            )
        )
        return checks

    def _check(
        self,
        name: str,
        dimension: str,
        passed: bool,
        evidence: str,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "dimension": dimension,
            "passed": bool(passed),
            "evidence": evidence,
        }

    def _dimensions(self, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for check in checks:
            grouped.setdefault(str(check["dimension"]), []).append(check)
        return [
            {
                "name": name,
                "score": self._score(
                    sum(1 for check in items if check["passed"]),
                    len(items),
                ),
                "check_count": len(items),
                "passed_count": sum(1 for check in items if check["passed"]),
            }
            for name, items in grouped.items()
        ]

    def _reply_limit(self, task: Task) -> int:
        return 20 if task.id == "course_live_upgrade" else 30

    def _score(self, passed: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return round(passed / total * 100, 1)

    def _conclusion(self, score: float) -> str:
        if score >= 90:
            return "整体遵循任务指令，关键流程和约束表现稳定。"
        if score >= 75:
            return "大部分指令可遵循，建议关注少量失败场景。"
        if score >= 60:
            return "存在明显分支或约束问题，需要针对失败证据优化。"
        return "任务达成风险较高，需要优先修复流程和约束遵守能力。"
