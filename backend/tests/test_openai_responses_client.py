from __future__ import annotations

import unittest

from backend.app.llm import OpenAIResponsesClient


class OpenAIResponsesClientTests(unittest.TestCase):
    def test_extracts_direct_output_text(self) -> None:
        self.assertEqual(
            OpenAIResponsesClient.extract_output_text({"output_text": "  result  "}),
            "result",
        )

    def test_extracts_message_content_blocks(self) -> None:
        payload = {
            "output": [
                {"type": "reasoning", "content": []},
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "第一段"},
                        {"type": "output_text", "text": "第二段"},
                    ],
                },
            ]
        }
        self.assertEqual(OpenAIResponsesClient.extract_output_text(payload), "第一段\n第二段")


if __name__ == "__main__":
    unittest.main()
