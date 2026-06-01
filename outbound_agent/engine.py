from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any

from outbound_agent.llm import LLMClient
from outbound_agent.models import Message, Session, Task


def load_tasks(path: Path) -> dict[str, Task]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {Task.from_dict(item).id: Task.from_dict(item) for item in data["tasks"]}


def has_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def render(template: str, variables: dict[str, str]) -> str:
    return Template(template).safe_substitute(variables)


@dataclass
class ReplyPlan:
    """Deterministic business decision; the LLM may only verbalize this plan."""

    intent: str
    status: str
    required_points: list[str]
    max_chars: int
    exact_text: str = ""
    forbidden: list[str] = field(default_factory=list)
    should_end: bool = False
    pause_after: bool = True

    def fallback_text(self) -> str:
        if self.exact_text:
            return self.exact_text
        text = "，".join(point.strip("。") for point in self.required_points if point.strip())
        return text or "我向同事确认后再回电给你。"

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "status": self.status,
            "required_points": self.required_points,
            "max_chars": self.max_chars,
            "exact_text": self.exact_text,
            "forbidden": self.forbidden,
            "should_end": self.should_end,
            "pause_after": self.pause_after,
        }


class AgentEngine:
    def __init__(self, tasks: dict[str, Task]) -> None:
        self.tasks = tasks
        self.llm = LLMClient()

    def start(self, session: Session) -> Message:
        task = self.tasks[session.task_id]
        session.variables = {**task.defaults(), **{k: str(v) for k, v in session.variables.items()}}
        opening = render(task.opening_line, session.variables)
        session.status = "开场"
        plan = ReplyPlan(
            intent="开场白",
            status="开场",
            required_points=[opening],
            exact_text=opening,
            max_chars=self._max_chars(task),
        )
        return self._reply_from_plan(task, session, "", plan)

    def message(self, session: Session, user_text: str) -> Message:
        task = self.tasks[session.task_id]
        session.add("user", user_text)
        if session.ended:
            plan = ReplyPlan(
                intent="通话已结束",
                status="已结束",
                required_points=["本次通话已结束。"],
                exact_text="本次通话已结束。",
                max_chars=20,
                should_end=True,
            )
            return self._reply_from_plan(task, session, user_text, plan)

        plan = self._plan(task, session, user_text)
        return self._reply_from_plan(task, session, user_text, plan)

    def _reply_from_plan(
        self,
        task: Task,
        session: Session,
        user_text: str,
        plan: ReplyPlan,
    ) -> Message:
        session.status = plan.status
        session.meta["reply_plan"] = plan.to_dict()

        if session.mode == "llm":
            try:
                raw = self._call_llm_voice_agent(task, session, user_text, plan)
                if not raw:
                    raise RuntimeError("LLM returned empty content")
                text = self._guard_reply(task, raw, plan)
                session.meta["last_reply_source"] = "llm"
                session.meta.pop("llm_error", None)
            except RuntimeError as exc:
                session.meta["last_reply_source"] = "llm_error"
                session.meta["llm_error"] = str(exc)
                text = f"大模型调用失败：{self._brief_error(exc)}"
        else:
            text = self._guard_reply(task, plan.fallback_text(), plan)
            session.meta["last_reply_source"] = "rule"

        if plan.should_end:
            session.ended = True
        return session.add("assistant", text)

    def _call_llm_voice_agent(
        self,
        task: Task,
        session: Session,
        user_text: str,
        plan: ReplyPlan,
    ) -> str:
        """Call the LLM for every voice-agent reply after code locks the business plan."""
        return self.llm.generate_voice_reply(task, session, user_text, plan.to_dict())

    def _guard_reply(self, task: Task, text: str, plan: ReplyPlan) -> str:
        text = self._sanitize_reply(task, text)

        # Some branches in the table require exact wording or exact hang-up wording.
        if plan.exact_text:
            return plan.exact_text

        if any(term and term in text for term in plan.forbidden):
            return self._clip(plan.fallback_text(), plan.max_chars)

        limit = plan.max_chars
        if len(text) > limit + 8:
            return self._clip(plan.fallback_text(), limit)
        return text

    def _sanitize_reply(self, task: Task, text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        if task.id == "course_live_upgrade":
            for banned in ["好的", "哈哈", "嘿嘿", "嘻嘻"]:
                text = text.replace(banned, "")
        return text.strip(" ，,")

    def _clip(self, text: str, limit: int) -> str:
        text = self._sanitize_reply(Task("", "", "", "", "", "", [], [], []), text)
        if len(text) <= limit:
            return text
        return text[: max(1, limit - 1)].rstrip("，。,. ") + "。"

    def _brief_error(self, exc: RuntimeError) -> str:
        text = re.sub(r"Bearer\s+\S+", "Bearer ***", str(exc))
        text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", text)
        if len(text) > 140:
            text = text[:137] + "..."
        return text

    def _max_chars(self, task: Task) -> int:
        return 20 if task.id == "course_live_upgrade" else 30

    def _plan(self, task: Task, session: Session, user_text: str) -> ReplyPlan:
        if task.id == "rider_flying_leg":
            return self._plan_rider(session, user_text)
        if task.id == "course_live_upgrade":
            return self._plan_course(session, user_text)
        return ReplyPlan(
            intent="职责外问题",
            status="职责外问题",
            required_points=["我向同事确认后再回电给你。我现在能回答的先回答。"],
            exact_text="我向同事确认后再回电给你。我现在能回答的先回答。",
            max_chars=40,
        )

    def _plan_rider(self, session: Session, user_text: str) -> ReplyPlan:
        text = user_text.strip().lower()
        v = session.variables
        strong_unable = has_any(text, ["肯定不", "确实不", "完全没法", "真跑不了", "不可能"])
        unable = has_any(text, ["不想", "没空", "不能", "无法", "不跑", "跑不了", "有事", "请假", "太累"])
        willing = has_any(text, ["可以", "能", "马上", "现在", "会跑", "去跑", "没问题", "上线"])

        wrong_number = (
            has_any(text, ["不是本人", "不是我", "我不是", "打错", "错号", "号码不对", "找错人", "不认识"])
            or text in {"不是", "不是的"}
        )

        if wrong_number:
            return ReplyPlan(
                intent="号码不匹配，结束通话",
                status="号码需核对",
                required_points=["打扰了，我再核对下号码。"],
                exact_text="打扰了，我再核对下号码。",
                max_chars=20,
                should_end=True,
            )
        if has_any(text, ["你是谁", "谁啊", "哪位", "你哪位", "什么事", "干嘛的", "找谁"]):
            rider_name = v.get("rider_name") or "您"
            return ReplyPlan(
                intent="说明坐席身份",
                status="身份说明",
                required_points=[f"我是站长，找{rider_name}确认飞毛腿合同"],
                max_chars=30,
            )
        if has_any(text, ["退出", "取消报名", "不参加"]):
            return ReplyPlan(
                intent="解释退出规则",
                status="解释退出规则",
                required_points=[f"退出需前一天{v['Z']}点前在App取消", "次日生效"],
                max_chars=30,
            )
        if has_any(text, ["为什么", "凭什么", "排名", "名额", "资格"]):
            return ReplyPlan(
                intent="解释飞毛腿资格规则",
                status="解释报名排名",
                required_points=["报名按排名进行", "不是站长干预"],
                max_chars=30,
            )
        if has_any(text, ["奖励", "补贴", "多钱", "多少钱", "加钱"]):
            return ReplyPlan(
                intent="解释奖励",
                status="解释奖励",
                required_points=[f"连续{v['W']}天达标", f"每单多{v['bonus']}元"],
                max_chars=30,
            )
        if has_any(text, ["几单", "多少单", "要求", "达标", "单量"]):
            return ReplyPlan(
                intent="解释单量要求",
                status="解释单量要求",
                required_points=[f"单日{v['X']}单", f"多日每天{v['Y']}单"],
                max_chars=30,
            )
        if has_any(text, ["安全", "下雨", "天气", "超时", "取消", "拒单"]):
            return ReplyPlan(
                intent="提醒配送注意事项",
                status="配送建议",
                required_points=["少拒单、取消、超时", "恶劣天气订单更多", "注意安全"],
                max_chars=30,
            )
        if unable:
            count = int(session.meta.get("unable_count", 0)) + 1
            session.meta["unable_count"] = count
            if count >= 2 or strong_unable:
                return ReplyPlan(
                    intent="骑手坚持无法配送，安慰后结束",
                    status="无法配送，结束",
                    required_points=["理解你确实不方便", "后续有空再报名"],
                    max_chars=30,
                    should_end=True,
                )
            return ReplyPlan(
                intent="挽留不想配送的骑手",
                status="挽留",
                required_points=["名额很紧", "能跑尽量跑一会儿"],
                max_chars=30,
            )
        if willing:
            session.stage = max(session.stage, 2)
            return ReplyPlan(
                intent="鼓励开始配送",
                status="已接受",
                required_points=["午晚高峰上线", "注意安全"],
                max_chars=30,
            )

        if session.stage == 0:
            session.stage = 1
            return ReplyPlan(
                intent="告知合同生效并确认能否开跑",
                status="确认开跑",
                required_points=["今天飞毛腿合同已生效", "询问能否开始配送"],
                max_chars=30,
            )
        if session.stage == 1:
            session.stage = 2
            return ReplyPlan(
                intent="说明连续配送要求",
                status="说明连续配送",
                required_points=[f"需要连续{v['Y']}天完成配送", "否则合同会受影响"],
                max_chars=30,
            )
        return ReplyPlan(
            intent="职责外问题",
            status="职责外问题",
            required_points=["我向同事确认后再回电给你。我现在能回答的先回答。"],
            exact_text="我向同事确认后再回电给你。我现在能回答的先回答。",
            max_chars=40,
        )

    def _plan_course(self, session: Session, user_text: str) -> ReplyPlan:
        text = user_text.strip().lower()

        if has_any(text, ["开车", "在路上", "驾驶"]):
            return ReplyPlan(
                intent="商家正在开车，礼貌挂断",
                status="对方开车，结束",
                required_points=["那我稍后再打"],
                exact_text="那我稍后再打",
                max_chars=20,
                should_end=True,
            )
        if has_any(text, ["忙", "没时间", "开会"]):
            return ReplyPlan(
                intent="老板忙，按要求简短挽留",
                status="忙碌挽留",
                required_points=["就1分钟，保证简短"],
                exact_text="就1分钟，保证简短",
                max_chars=20,
            )
        if has_any(text, ["优惠券", "折扣券", "优惠", "券"]):
            return ReplyPlan(
                intent="拒绝承诺优惠券",
                status="优惠约束",
                required_points=["不能承诺优惠券"],
                max_chars=20,
                forbidden=["折扣券已发", "优惠券已发", "送券", "赠券"],
            )
        if has_any(text, ["价格", "费用", "贵", "收费", "多少钱"]):
            return ReplyPlan(
                intent="解释价格",
                status="解释价格",
                required_points=["标准直播更便宜", "低延迟费用略高"],
                max_chars=20,
            )
        if has_any(text, ["区别", "差别", "不同", "标准直播", "低延迟"]):
            return ReplyPlan(
                intent="解释直播区别",
                status="解释区别",
                required_points=["标准延迟5到10秒", "低延迟1到2秒", "互动课选低延迟"],
                max_chars=20,
            )
        if has_any(text, ["为什么", "之前", "后台"]):
            return ReplyPlan(
                intent="解释此前后台线路",
                status="解释历史低延迟",
                required_points=["之前前端未开放", "临时低延迟是为保障同步"],
                max_chars=20,
            )

        guide = session.meta.get("guide")
        if guide == "third_party":
            return self._next_guide(
                session,
                [
                    "进入【我的】",
                    "点击【服务商/直播平台管理】",
                    "选择【直播平台】",
                    "勾选低延迟直播并保存",
                ],
                next_stage=8,
                next_status="第三方开通完成",
            )
        if guide == "fee":
            return self._next_guide(
                session,
                [
                    "进入【教务/财务设置】",
                    "打开【收费规则】",
                    "编辑附加费并启用低延迟",
                    "保存设置",
                ],
                next_stage=10,
                next_status="费用设置完成",
            )

        if session.stage == 0:
            session.stage = 1
            if has_any(text, ["不是", "不负责", "转达"]):
                return ReplyPlan(
                    intent="非负责人，请其转达",
                    status="身份已处理",
                    required_points=["麻烦转达", "新增低延迟直播独立选项"],
                    max_chars=20,
                )
            return ReplyPlan(
                intent="负责人确认后传达升级概览",
                status="身份已处理",
                required_points=["直播产品升级", "低延迟会单独显示"],
                max_chars=20,
            )
        if session.stage == 1:
            session.stage = 2
            return ReplyPlan(
                intent="确认是否知情",
                status="确认是否知情",
                required_points=["之前后台已走低延迟", "询问是否知道"],
                max_chars=20,
            )
        if session.stage == 2:
            session.stage = 3
            if has_any(text, ["不知", "不知道", "不清楚", "没有"]):
                return ReplyPlan(
                    intent="解释此前未开放原因",
                    status="传达升级",
                    required_points=["前端当时未开放", "临时开启是保障同步"],
                    max_chars=20,
                )
            return ReplyPlan(
                intent="传达发布页升级",
                status="传达升级",
                required_points=["之后发布页分开显示两个选项"],
                max_chars=20,
            )
        if session.stage == 3:
            session.stage = 4
            return ReplyPlan(
                intent="说明标准直播",
                status="说明标准直播",
                required_points=["标准直播费用低", "延迟5到10秒", "适合大班课"],
                max_chars=20,
            )
        if session.stage == 4:
            session.stage = 5
            return ReplyPlan(
                intent="说明低延迟直播",
                status="说明低延迟直播",
                required_points=["低延迟1到2秒", "互动更顺", "适合小班实操课"],
                max_chars=20,
            )
        if session.stage == 5:
            session.stage = 6
            return ReplyPlan(
                intent="询问发布方式",
                status="确认发布方式",
                required_points=["询问使用Web控制台、校务系统A还是SaaS系统B"],
                max_chars=20,
            )
        if session.stage == 6:
            session.stage = 7
            if has_any(text, ["web", "控制台"]):
                if has_any(text, ["看不到", "没有", "未显示"]):
                    return ReplyPlan(
                        intent="Web未显示，后台配置",
                        status="处理发布入口",
                        required_points=["后台为您配置", "明天再查看"],
                        max_chars=20,
                    )
                return ReplyPlan(
                    intent="Web已显示，直接使用",
                    status="处理发布入口",
                    required_points=["能看到就直接选择"],
                    max_chars=20,
                )
            if has_any(text, ["系统a", "saas", "系统b", "第三方", "a", "b"]):
                if has_any(text, ["看不到", "没有", "未显示"]):
                    session.meta["guide"] = "third_party"
                    session.meta["guide_index"] = 0
                    return ReplyPlan(
                        intent="第三方系统未显示，准备引导开通",
                        status="第三方引导准备",
                        required_points=["我带您开通", "每步慢慢来"],
                        max_chars=20,
                    )
                return ReplyPlan(
                    intent="第三方已显示，按需选择",
                    status="处理发布入口",
                    required_points=["按课程需要选择即可"],
                    max_chars=20,
                )
            return ReplyPlan(
                intent="发布方式不清，继续确认",
                status="确认发布方式",
                required_points=["再确认是Web、系统A还是SaaS B"],
                max_chars=20,
            )
        if session.stage == 7:
            session.stage = 8
            return ReplyPlan(
                intent="检查学员端费用",
                status="检查附加费",
                required_points=["询问学员端是否有线路附加费"],
                max_chars=20,
            )
        if session.stage == 8:
            session.stage = 9
            if has_any(text, ["有", "设置了", "收"]):
                return ReplyPlan(
                    intent="提醒费用适用",
                    status="处理附加费",
                    required_points=["确认低延迟也启用该费用"],
                    max_chars=20,
                )
            if has_any(text, ["不会", "不能", "找不到"]):
                session.meta["guide"] = "fee"
                session.meta["guide_index"] = 0
                return ReplyPlan(
                    intent="无法配置费用，准备引导",
                    status="费用引导准备",
                    required_points=["我带您设置", "每步慢慢来"],
                    max_chars=20,
                )
            return ReplyPlan(
                intent="未设置费用，跳过",
                status="处理附加费",
                required_points=["未设置就先不用处理"],
                max_chars=20,
            )
        if session.stage == 9:
            session.stage = 10
            return ReplyPlan(
                intent="询问企业微信添加",
                status="企业微信",
                required_points=["询问当前号码能否添加企微"],
                max_chars=20,
            )
        if session.stage == 10:
            session.stage = 11
            if has_any(text, ["不能", "不行", "换", "别的"]):
                return ReplyPlan(
                    intent="索要可添加手机号",
                    status="企微处理",
                    required_points=["请提供可加企微的手机号"],
                    max_chars=20,
                )
            return ReplyPlan(
                intent="提示通过企微",
                status="企微处理",
                required_points=["稍后添加企业微信", "请通过验证"],
                max_chars=20,
            )

        return ReplyPlan(
            intent="结束通话",
            status="完成",
            required_points=["祝课程顺利、招生满满"],
            exact_text="祝课程顺利、招生满满",
            max_chars=20,
            should_end=True,
        )

    def _next_guide(
        self,
        session: Session,
        steps: list[str],
        next_stage: int,
        next_status: str,
    ) -> ReplyPlan:
        index = int(session.meta.get("guide_index", 0))
        if index < len(steps):
            session.meta["guide_index"] = index + 1
            return ReplyPlan(
                intent=f"慢速引导第{index + 1}步",
                status=f"引导{index + 1}/{len(steps)}",
                required_points=[steps[index], "说完后暂停等待"],
                max_chars=20,
            )
        session.meta.pop("guide", None)
        session.meta.pop("guide_index", None)
        session.stage = next_stage
        return ReplyPlan(
            intent="引导完成",
            status=next_status,
            required_points=["这一步完成了"],
            max_chars=20,
        )
