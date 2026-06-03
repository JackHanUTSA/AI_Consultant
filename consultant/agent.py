"""Tool-use loop driving the consultant conversation.

Provider is selected by the `PROVIDER` env var: `anthropic` (default) or `openai`.
Both paths use native function/tool calling. Messages are persisted in
Anthropic-shaped content blocks regardless of provider; the OpenAI path
converts in/out so a conversation could in principle resume on either backend
(though switching mid-case is not a supported flow).
"""
from __future__ import annotations

import json
import os

from consultant.prompts import SYSTEM_PROMPT
from consultant.tools import TOOLS, dispatch_tool


ANTHROPIC_MODEL = "claude-sonnet-4-6"
OPENAI_MODEL = "gpt-4o"
MAX_TOKENS = 4096


class ConsultantAgent:
    def __init__(self, student: dict, db):
        self.student = student
        self.db = db
        self.messages: list = student["conversation"]
        self.provider = (os.environ.get("PROVIDER") or "anthropic").lower()

        if self.provider == "openai":
            from openai import OpenAI
            self.client = OpenAI()
        elif self.provider == "anthropic":
            from anthropic import Anthropic
            self.client = Anthropic()
        else:
            raise ValueError(
                f"Unknown PROVIDER={self.provider!r}. Use 'anthropic' or 'openai'."
            )

    def _profile_block_text(self) -> str:
        profile_str = json.dumps(self.student["profile"], indent=2)
        return (
            f"<student_name>{self.student['name']}</student_name>\n"
            f"<current_profile>\n{profile_str}\n</current_profile>"
        )

    def _anthropic_system_blocks(self) -> list:
        return [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": self._profile_block_text()},
        ]

    def _openai_system_text(self) -> str:
        return SYSTEM_PROMPT + "\n\n" + self._profile_block_text()

    def _run_turn(self) -> None:
        if self.provider == "openai":
            self._run_turn_openai()
        else:
            self._run_turn_anthropic()
        self.db.save_conversation(self.student["id"], self.messages)
        self.db.save_profile(self.student["id"], self.student["profile"])

    def _run_turn_anthropic(self) -> None:
        while True:
            response = self.client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=MAX_TOKENS,
                system=self._anthropic_system_blocks(),
                tools=TOOLS,
                messages=self.messages,
            )

            assistant_content = [block.model_dump() for block in response.content]
            self.messages.append({"role": "assistant", "content": assistant_content})

            for block in response.content:
                if block.type == "text" and block.text.strip():
                    print(f"\nConsultant: {block.text}\n")

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = dispatch_tool(
                            block.name, block.input, self.student, self.db
                        )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            }
                        )
                self.messages.append({"role": "user", "content": tool_results})
                continue

            break

    def _run_turn_openai(self) -> None:
        oai_tools = [_to_openai_tool(t) for t in TOOLS]
        while True:
            oai_messages = _to_openai_messages(
                self.messages, system_text=self._openai_system_text()
            )
            response = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                max_tokens=MAX_TOKENS,
                tools=oai_tools,
                messages=oai_messages,
            )
            msg = response.choices[0].message
            finish = response.choices[0].finish_reason

            # Re-record assistant turn in Anthropic content-block shape.
            content_blocks: list[dict] = []
            if msg.content:
                content_blocks.append({"type": "text", "text": msg.content})
            for tc in (msg.tool_calls or []):
                try:
                    parsed_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    parsed_args = {}
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": parsed_args,
                    }
                )
            self.messages.append({"role": "assistant", "content": content_blocks})

            if msg.content and msg.content.strip():
                print(f"\nConsultant: {msg.content}\n")

            if finish == "tool_calls" and msg.tool_calls:
                tool_results = []
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = dispatch_tool(
                        tc.function.name, args, self.student, self.db
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": result,
                        }
                    )
                self.messages.append({"role": "user", "content": tool_results})
                continue

            break

    def chat_loop(self) -> None:
        if not self.messages:
            self.messages.append(
                {
                    "role": "user",
                    "content": "Hi — let's begin the consultation. I'm ready when you are.",
                }
            )
            self._run_turn()

        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                print()
                break
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "bye"):
                print("Saved. Talk soon!")
                break
            self.messages.append({"role": "user", "content": user_input})
            self._run_turn()


def _to_openai_tool(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


def _to_openai_messages(messages: list, system_text: str) -> list:
    """Convert persisted Anthropic-shape messages → OpenAI chat-completions shape."""
    out: list = [{"role": "system", "content": system_text}]
    for m in messages:
        content = m["content"]
        if m["role"] == "user":
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block["content"],
                        }
                    )
                elif block.get("type") == "text":
                    out.append({"role": "user", "content": block["text"]})
        elif m["role"] == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        }
                    )
            assistant_msg: dict = {"role": "assistant"}
            assistant_msg["content"] = "\n".join(p for p in text_parts if p) or None
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            out.append(assistant_msg)
    return out
