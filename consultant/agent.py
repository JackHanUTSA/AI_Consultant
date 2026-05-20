"""Anthropic tool-use loop driving the consultant conversation."""
import json

from anthropic import Anthropic

from consultant.prompts import SYSTEM_PROMPT
from consultant.tools import TOOLS, dispatch_tool


MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096


class ConsultantAgent:
    def __init__(self, student: dict, db):
        self.student = student
        self.db = db
        self.client = Anthropic()
        self.messages: list = student["conversation"]

    def _system_blocks(self) -> list:
        profile_str = json.dumps(self.student["profile"], indent=2)
        return [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": (
                    f"<student_name>{self.student['name']}</student_name>\n"
                    f"<current_profile>\n{profile_str}\n</current_profile>"
                ),
            },
        ]

    def _run_turn(self) -> None:
        while True:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=self._system_blocks(),
                tools=TOOLS,
                messages=self.messages,
            )

            # Persist assistant message as plain dicts so it round-trips through JSON.
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

        self.db.save_conversation(self.student["id"], self.messages)
        self.db.save_profile(self.student["id"], self.student["profile"])

    def chat_loop(self) -> None:
        # Prime the conversation if this is a fresh case so the consultant opens.
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
