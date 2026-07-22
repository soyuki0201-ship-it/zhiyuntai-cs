"""Prompt 构造器

根据对话上下文、知识片段、系统指令构造发给 DeepSeek 的完整 Prompt。
"""


class PromptBuilder:
    """Prompt 构造器"""

    SYSTEM_PROMPT = (
        "你叫智云台助手，是智云台产品的AI客服。你的语气友好亲切、自然。\n"
        "你的回答要简洁清晰，基于参考知识回答问题，不要编造信息。\n"
        "如果参考知识足够回答用户问题，请直接回答，不需要提及'根据参考知识'。\n"
        "如果参考知识不足以回答，或者用户问题超出了你的能力范围，\n"
        "请明确说'这个问题我需要转给人工客服处理'，不要强行回答。\n"
        "当用户发来图片提取的文字时，结合图片中的文字信息一起理解问题。"
    )

    WAITING_PROMPT = (
        "\n\n【等待期策略 - 仅当已触发转人工但运营尚未接管时生效】\n"
        "你已经判断需要人工处理，但仍然可以和客户继续对话：\n"
        "1. 安抚客户情绪，告知'已经通知客服同事了'\n"
        "2. 如果客户提出新问题且在知识范围内，仍然回答\n"
        "3. 可以主动收集客户信息（名称、问题描述等）帮助客服更快处理\n"
        "4. 不要替客服做出任何承诺（赔偿、退款、时限保证等）"
    )

    @classmethod
    def build_messages(
        cls,
        user_input: str,
        knowledge_chunks: list[dict] = None,
        conversation_history: list[dict] = None,
        is_handoff_waiting: bool = False,
    ) -> list[dict]:
        """构造完整的对话消息列表

        Args:
            user_input: 用户当前输入
            knowledge_chunks: RAG 检索到的知识片段
            conversation_history: 对话历史
            is_handoff_waiting: 是否在等待人工接管的等待期

        Returns:
            list[dict]: messages 列表，可直接传给 DeepSeek API
        """
        system = cls.SYSTEM_PROMPT
        if is_handoff_waiting:
            system += cls.WAITING_PROMPT

        messages = [{"role": "system", "content": system}]

        if knowledge_chunks:
            knowledge_text = "\n\n参考知识：\n"
            for chunk in knowledge_chunks:
                source_info = ""
                if chunk.get("metadata", {}).get("title"):
                    source_info = f"（来源：{chunk['metadata']['title']}）"
                knowledge_text += f"- {chunk['document']} {source_info}\n"
            messages.append({"role": "system", "content": knowledge_text.strip()})

        if conversation_history:
            for msg in conversation_history[-20:]:
                messages.append(msg)

        messages.append({"role": "user", "content": user_input})
        return messages

    @classmethod
    def check_should_handoff(cls, ai_reply: str) -> bool:
        """检查 AI 回复是否表达了需要转人工

        Args:
            ai_reply: AI 生成的回复

        Returns:
            bool: 是否需要转人工
        """
        handoff_markers = [
            "转给人工客服",
            "已转给人工客服",
            "转人工客服处理",
            "我无法确定",
            "无法回答这个问题",
            "需要转给人工",
            "需要人工客服",
        ]
        return any(marker in ai_reply for marker in handoff_markers)
