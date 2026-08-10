"""批量脚本只负责把目录参数转交给统一入口。"""

from __future__ import annotations

import unittest

from scripts.run_batch import _build_parser, _main_argv


class BatchEntryTest(unittest.TestCase):
    def test_batch_arguments_reuse_main_directory_mode(self) -> None:
        args = _build_parser().parse_args(["--reports_path", "/data/incoming", "--policy-rules", "/data/policy.xlsx", "--use-llm", "--strict-llm", "--continue-on-error"])
        argv = _main_argv(args)
        self.assertEqual(argv[:4], ["--reports_path", "/data/incoming", "--policy-rules", "/data/policy.xlsx"])
        self.assertIn("--use-llm", argv)
        self.assertIn("--strict-llm", argv)
        self.assertIn("--continue-on-error", argv)
        self.assertNotIn("--case-id", argv)


if __name__ == "__main__":
    unittest.main()
