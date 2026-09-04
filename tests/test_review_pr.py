"""Tests locales para review_pr.py, sin llamadas reales a GitHub ni Groq."""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import review_pr  # noqa: E402


SAMPLE_DIFF = """\
diff --git a/app.py b/app.py
index e69de29..4b825dc 100644
--- a/app.py
+++ b/app.py
@@ -1,3 +1,6 @@
 def divide(a, b):
-    return a / b
+    if b == 0:
+        return None
+    return a / b
"""


class TruncateDiffTests(unittest.TestCase):
    def test_no_truncation_when_short(self):
        diff, truncated = review_pr.truncate_diff("short diff", max_chars=100)
        self.assertEqual(diff, "short diff")
        self.assertFalse(truncated)

    def test_truncates_long_diff(self):
        long_diff = "x" * 500
        diff, truncated = review_pr.truncate_diff(long_diff, max_chars=100)
        self.assertEqual(len(diff), 100)
        self.assertTrue(truncated)


class FormatCommentTests(unittest.TestCase):
    def test_includes_model_name_and_footer(self):
        comment = review_pr.format_comment("## Resumen\nTodo bien.")
        self.assertIn("CodeGuard AI Review", comment)
        self.assertIn(review_pr.GROQ_MODEL, comment)
        self.assertIn("Todo bien.", comment)


class MainFlowTests(unittest.TestCase):
    """Simula el flujo completo con requests.get/post mockeados."""

    def setUp(self):
        self.env_patcher = patch.dict(
            os.environ,
            {
                "GITHUB_TOKEN": "fake-github-token",
                "GROQ_API_KEY": "fake-groq-key",
                "GITHUB_REPOSITORY": "sergio/CodeGuard",
                "PR_NUMBER": "42",
            },
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    @patch("review_pr.requests.post")
    @patch("review_pr.requests.get")
    def test_full_review_flow(self, mock_get, mock_post):
        mock_get.return_value = MagicMock(status_code=200, text=SAMPLE_DIFF)

        groq_response = MagicMock(status_code=200)
        groq_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            "## Resumen\nSe añade validación de división por cero.\n\n"
                            "## Posibles bugs o problemas de lógica\n"
                            "No se detectaron problemas evidentes.\n\n"
                            "## Sugerencias de estilo y buenas prácticas\n"
                            "Sin sugerencias adicionales."
                        )
                    }
                }
            ]
        }
        comment_response = MagicMock(status_code=201)
        mock_post.side_effect = [groq_response, comment_response]

        review_pr.main()

        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(mock_post.call_count, 2)

        groq_call = mock_post.call_args_list[0]
        self.assertEqual(groq_call.args[0], review_pr.GROQ_API_URL)
        self.assertIn("divide(a, b)", groq_call.kwargs["json"]["messages"][1]["content"])

        comment_call = mock_post.call_args_list[1]
        posted_body = comment_call.kwargs["json"]["body"]
        self.assertIn("Se añade validación de división por cero.", posted_body)

    @patch("review_pr.requests.post")
    @patch("review_pr.requests.get")
    def test_empty_diff_posts_notice_without_calling_groq(self, mock_get, mock_post):
        mock_get.return_value = MagicMock(status_code=200, text="")
        mock_post.return_value = MagicMock(status_code=201)

        review_pr.main()

        mock_post.assert_called_once()
        posted_body = mock_post.call_args.kwargs["json"]["body"]
        self.assertIn("No se detectaron cambios", posted_body)

    @patch("review_pr.requests.get")
    def test_github_api_error_exits_with_code_1(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404, text="Not Found")

        with self.assertRaises(SystemExit) as ctx:
            review_pr.main()
        self.assertEqual(ctx.exception.code, 1)

    def test_missing_api_key_raises_review_error(self):
        del os.environ["GROQ_API_KEY"]
        with self.assertRaises(SystemExit) as ctx:
            review_pr.main()
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
