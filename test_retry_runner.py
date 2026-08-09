import os
import csv
import json
import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest import mock

import retry_runner


class MediaDelayTests(unittest.TestCase):
    class Process:
        def __init__(self, lines):
            self.stdout = iter(lines)
            self.signals = []

        def send_signal(self, value):
            self.signals.append(value)

        def wait(self):
            return 0

    def test_media_delay_parser_accepts_fixed_and_range_and_rejects_invalid(self):
        self.assertEqual(retry_runner.parse_media_delay("3"), (3.0, 3.0))
        self.assertEqual(retry_runner.parse_media_delay("2-5"), (2.0, 5.0))
        self.assertIsNone(retry_runner.parse_media_delay(""))
        for value in ("-1", "5-2", "nan", "x-y"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                retry_runner.parse_media_delay(value)

    def test_media_delay_sleeps_once_between_terminal_media_and_not_after_last(self):
        prepare = f'{retry_runner.MEDIA_PREPARE_PREFIX} "video"\n'
        prefix = retry_runner.STATUS_PREFIX
        lines = [
            prepare,
            f'{prefix} DOWNLOADED "1111111111" "/downloads/a.mp4" "video"\n',
            prepare,
            f'{prefix} SKIPPED "2222222222" "/downloads/b.mp4" "video"\n',
            prepare,
            f'{prefix} FAILED "3333333333" "" "video"\n',
        ]
        process = self.Process(lines)
        sleeper = mock.Mock()
        with mock.patch.object(retry_runner.subprocess, "Popen", return_value=process):
            _, _, counts, _, _ = retry_runner.run(
                ["gallery-dl"], {}, media_delay=(2.0, 5.0),
                sleep=sleeper, rng=lambda low, high: 3.5,
            )

        self.assertEqual(counts, {"DOWNLOADED": 1, "SKIPPED": 1, "FAILED": 1})
        self.assertEqual([call.args[0] for call in sleeper.call_args_list], [3.5, 3.5])
        self.assertEqual(
            process.signals,
            [
                retry_runner.SUSPEND_SIGNAL, retry_runner.RESUME_SIGNAL,
                retry_runner.SUSPEND_SIGNAL, retry_runner.RESUME_SIGNAL,
            ],
        )

    def test_single_terminal_media_has_no_media_delay_or_process_signal(self):
        process = self.Process([
            f'{retry_runner.MEDIA_PREPARE_PREFIX} "video"\n',
            f'{retry_runner.STATUS_PREFIX} DOWNLOADED "1111111111" "/downloads/a.mp4" "video"\n',
        ])
        sleeper = mock.Mock()
        with mock.patch.object(retry_runner.subprocess, "Popen", return_value=process):
            retry_runner.run(
                ["gallery-dl"], {}, media_delay=(2.0, 5.0), sleep=sleeper
            )

        sleeper.assert_not_called()
        self.assertEqual(process.signals, [])

    def test_media_delay_is_forwarded_while_sleep_request_remains_gallery_option(self):
        success = (0, set(), {"DOWNLOADED": 1, "SKIPPED": 0, "FAILED": 0}, False, None)
        common = ["--sleep-request", "7-9", *retry_runner.status_options()]
        with mock.patch.dict(os.environ, {"TIKTOK_FORCE_FALLBACK": "1"}, clear=False), \
                mock.patch.object(retry_runner, "run", return_value=success) as run:
            retry_runner.run_profile(
                "gallery-dl", common, [], "https://www.tiktok.com/@alice", {},
                media_delay=(2.0, 5.0),
            )

        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--sleep-request") + 1], "7-9")
        self.assertEqual(run.call_args.kwargs["media_delay"], (2.0, 5.0))
        self.assertIn(f"prepare:{retry_runner.MEDIA_PREPARE_PREFIX} {{subcategory!j}}", command)


class NewItemsTests(unittest.TestCase):
    class Process:
        def __init__(self, lines, rc=0):
            self.stdout = iter(lines)
            self.rc = rc
            self.terminated = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return self.rc

    def test_parse_new_items_accepts_positive_integer_and_removes_wrapper_option(self):
        self.assertEqual(
            retry_runner.parse_new_items(["--new-items", "3", "--write-metadata"]),
            (["--write-metadata"], 3),
        )
        self.assertEqual(retry_runner.parse_new_items(["--new-items=2"]), ([], 2))
        for args in (["--new-items"], ["--new-items", "0"], ["--new-items", "x"]):
            with self.subTest(args=args), self.assertRaises(ValueError):
                retry_runner.parse_new_items(args)

    def test_new_items_rejects_native_range_instead_of_combining_silently(self):
        for args in (["--new-items", "2", "--range", "1-9"], ["--range=1-9", "--new-items=2"]):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "--range"):
                retry_runner.parse_new_items(args)

    def test_quota_counts_only_downloaded_non_avatar_and_terminates_process(self):
        prefix = retry_runner.STATUS_PREFIX
        lines = [
            f'{prefix} DOWNLOADED "9999999999" "/downloads/avatar.jpg" "avatar"\n',
            f'{prefix} SKIPPED "1111111111" "/downloads/old.mp4" "video"\n',
            f'{prefix} DOWNLOADED "2222222222" "/downloads/new1.mp4" "video"\n',
            f'{prefix} DOWNLOADED "3333333333" "/downloads/new2.mp4" "video"\n',
            f'{prefix} DOWNLOADED "4444444444" "/downloads/too-many.mp4" "video"\n',
        ]
        process = self.Process(lines, rc=-15)
        with mock.patch.object(retry_runner.subprocess, "Popen", return_value=process) as popen:
            rc, _, counts, profile_failed, _ = retry_runner.run(
                ["gallery-dl"], {}, new_items=2
            )

        self.assertTrue(process.terminated)
        self.assertEqual(rc, 0)
        self.assertFalse(profile_failed)
        self.assertEqual(counts, {"DOWNLOADED": 2, "SKIPPED": 1, "FAILED": 0})
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_content_exhaustion_before_quota_is_success_with_real_count(self):
        process = self.Process([
            f'{retry_runner.STATUS_PREFIX} DOWNLOADED "2222222222" "/downloads/new.mp4" "video"\n'
        ])
        with mock.patch.object(retry_runner.subprocess, "Popen", return_value=process):
            rc, _, counts, profile_failed, _ = retry_runner.run(
                ["gallery-dl"], {}, new_items=3
            )

        self.assertFalse(process.terminated)
        self.assertEqual((rc, profile_failed, counts["DOWNLOADED"]), (0, False, 1))

    def test_single_and_batch_cli_forward_quota_without_forwarding_wrapper_flag(self):
        result = (0, {"DOWNLOADED": 2, "SKIPPED": 3, "FAILED": 0}, "gallery-dl")
        with mock.patch.object(retry_runner, "execute_target", return_value=result) as execute:
            self.assertEqual(retry_runner.main(["alice", "--new-items", "2"]), 0)
        execute.assert_called_once_with("alice", [], new_items=2)

        with mock.patch.object(retry_runner, "read_target_file", return_value=["alice"]), \
                mock.patch.object(retry_runner, "run_batch", return_value=0) as batch:
            self.assertEqual(
                retry_runner.main(["from-file", "/input/targets.txt", "--new-items=2"]), 0
            )
        batch.assert_called_once_with(["alice"], [], new_items=2)

    def test_native_and_fallback_share_remaining_new_item_quota(self):
        partial = (1, set(), {"DOWNLOADED": 1, "SKIPPED": 4, "FAILED": 0}, True, "retryable")
        fallback = (0, set(), {"DOWNLOADED": 1, "SKIPPED": 2, "FAILED": 0}, False, None)
        with mock.patch.dict(os.environ, {"PROFILE_MAX_ATTEMPTS": "1"}, clear=False), \
                mock.patch.object(retry_runner, "run", side_effect=[partial, fallback]) as run:
            rc, totals, backend = retry_runner.run_profile(
                "gallery-dl", [], [], "https://www.tiktok.com/@alice", {}, new_items=2
            )

        self.assertEqual((rc, totals["DOWNLOADED"], backend), (0, 2, "yt-dlp"))
        self.assertEqual(run.call_args_list[0].kwargs["new_items"], 2)
        self.assertEqual(run.call_args_list[1].kwargs["new_items"], 1)


class ProfileFallbackTests(unittest.TestCase):
    def test_docker_context_is_allowlisted_to_prevent_local_data_and_secret_leaks(self):
        dockerignore = Path(__file__).with_name(".dockerignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(dockerignore[0], "*")
        self.assertEqual(
            set(line for line in dockerignore if line.startswith("!")),
            {"!Dockerfile", "!docker-entrypoint.sh", "!retry_runner.py"},
        )
        self.assertNotIn("!targets.txt", dockerignore)
        self.assertNotIn("!downloads", dockerignore)

    def test_dockerfile_pins_forks_and_uses_buildkit_secret_for_private_fetch(self):
        dockerfile = Path(__file__).with_name("Dockerfile").read_text(encoding="utf-8")
        self.assertIn("GALLERY_DL_REF=48f9f648a5123432458acf121efa9151fda8eba8", dockerfile)
        self.assertIn("YT_DLP_REF=5d6b8c8cd19785c3086ae3a9ec618c45e25eb3bc", dockerfile)
        self.assertIn("--mount=type=secret,id=github_token,required=true", dockerfile)
        self.assertIn('test "$(git -C gallery-dl rev-parse HEAD)" = "$GALLERY_DL_REF"', dockerfile)
        self.assertIn('test "$(git -C yt-dlp rev-parse HEAD)" = "$YT_DLP_REF"', dockerfile)
        self.assertNotRegex(dockerfile, r"(?m)^(?:ARG|ENV)\s+(?:GH_TOKEN|GITHUB_TOKEN)")

    def test_total_profile_failure_without_item_ids_counts_one_failure(self):
        profile_failure = (
            0,
            set(),
            {"DOWNLOADED": 0, "SKIPPED": 0, "FAILED": 0},
            True,
            "retryable",
        )
        with mock.patch.dict(os.environ, {
            "PROFILE_MAX_ATTEMPTS": "1", "TIKTOK_FORCE_FALLBACK": "1"
        }, clear=False), mock.patch.object(
            retry_runner, "run", return_value=profile_failure
        ):
            rc, totals, backend = retry_runner.run_profile(
                "gallery-dl", [], [], "https://www.tiktok.com/@missing", {}
            )

        self.assertEqual(rc, 1)
        self.assertEqual(backend, "yt-dlp")
        self.assertEqual(totals, {"DOWNLOADED": 0, "SKIPPED": 0, "FAILED": 1})

    def test_socks5h_proxy_is_forwarded_to_native_and_ytdlp_fallback(self):
        fallback_success = (0, set(), {"DOWNLOADED": 1, "SKIPPED": 0, "FAILED": 0}, False, None)
        proxy = retry_runner.proxy_url({"SOCKS_PROXY_URL": "socks5h://proxy:1080"})
        with mock.patch.dict(os.environ, {"TIKTOK_FORCE_FALLBACK": "1"}, clear=False), \
                mock.patch.object(retry_runner, "run", return_value=fallback_success) as run:
            retry_runner.run_profile(
                "gallery-dl", ["--proxy", proxy], [],
                "https://www.tiktok.com/@test", {}, proxy,
            )

        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--proxy") + 1], proxy)
        fallback_option = next(value for value in command if "cmdline-args=" in value)
        self.assertIn(f"--proxy {proxy}", fallback_option)

    def test_invalid_proxy_is_rejected(self):
        with self.assertRaises(ValueError):
            retry_runner.proxy_url({"SOCKS_PROXY_URL": "socks5h://"})

    def test_retries_profile_with_exponential_delays_then_uses_ytdlp(self):
        native_failure = (0, set(), {"DOWNLOADED": 0, "SKIPPED": 0, "FAILED": 0}, True, "retryable")
        fallback_success = (0, set(), {"DOWNLOADED": 1, "SKIPPED": 0, "FAILED": 0}, False, None)
        with mock.patch.dict(os.environ, {
            "PROFILE_MAX_ATTEMPTS": "3", "PROFILE_BASE_DELAY": "2", "RETRY_JITTER": "0"
        }, clear=False), mock.patch.object(
            retry_runner, "run", side_effect=[native_failure] * 3 + [fallback_success]
        ) as run, mock.patch.object(retry_runner.time, "sleep") as sleep:
            rc, totals, backend = retry_runner.run_profile(
                "gallery-dl", ["--sleep-request", "2-5"], ["--range", "1"],
                "https://www.tiktok.com/@test", {},
            )

        self.assertEqual((rc, backend), (0, "yt-dlp"))
        self.assertEqual(totals["DOWNLOADED"], 1)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])
        fallback_command = run.call_args_list[-1].args[0]
        self.assertIn("extractor.tiktok.posts.ytdl=true", fallback_command)
        self.assertIn("extractor.tiktok.posts.module=yt_dlp", fallback_command)
        self.assertIn(
            "extractor.tiktok.posts.cmdline-args=--impersonate chrome",
            fallback_command,
        )
        self.assertLess(fallback_command.index("--range"), len(fallback_command))

    def test_forced_fallback_is_deterministic_and_skips_native_attempts(self):
        fallback_success = (0, set(), {"DOWNLOADED": 0, "SKIPPED": 1, "FAILED": 0}, False, None)
        with mock.patch.dict(os.environ, {"TIKTOK_FORCE_FALLBACK": "1"}, clear=False), \
                mock.patch.object(retry_runner, "run", return_value=fallback_success) as run, \
                mock.patch.object(retry_runner.time, "sleep") as sleep:
            rc, totals, backend = retry_runner.run_profile(
                "gallery-dl", [], [], "https://www.tiktok.com/@test", {}
            )

        self.assertEqual((rc, backend, totals["SKIPPED"]), (0, "yt-dlp", 1))
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    def test_native_success_does_not_invoke_fallback(self):
        native_success = (0, set(), {"DOWNLOADED": 0, "SKIPPED": 1, "FAILED": 0}, False, None)
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(retry_runner, "run", return_value=native_success) as run:
            rc, totals, backend = retry_runner.run_profile(
                "gallery-dl", [], [], "https://www.tiktok.com/@test", {}
            )

        self.assertEqual((rc, backend, totals["SKIPPED"]), (0, "gallery-dl", 1))
        self.assertEqual(run.call_count, 1)

    def test_retryable_tiktok_and_network_failures_rotate_tor_identity(self):
        proxy = "socks5h://original:secret@tor:9050"
        rotated = "socks5h://tiktok-new:new@tor:9050"
        for message in (
            "Failed to solve JavaScript challenge", "HTTP Error 403",
            "HTTP Error 429", "request timed out",
        ):
            with self.subTest(message=message):
                kind = retry_runner.classify_failure(message)
                self.assertEqual(kind, "retryable")
                failure = (0, set(), {"DOWNLOADED": 0, "SKIPPED": 0, "FAILED": 0}, True, kind)
                success = (0, set(), {"DOWNLOADED": 1, "SKIPPED": 0, "FAILED": 0}, False, None)
                with mock.patch.dict(os.environ, {
                    "PROFILE_MAX_ATTEMPTS": "2", "PROFILE_BASE_DELAY": "0", "RETRY_JITTER": "0"
                }, clear=False), mock.patch.object(
                    retry_runner, "run", side_effect=[failure, success]
                ) as run, mock.patch.object(
                    retry_runner, "isolated_proxy", return_value=rotated
                ) as isolate:
                    retry_runner.run_profile(
                        "gallery-dl", ["--proxy", proxy], [],
                        "https://www.tiktok.com/@test", {}, proxy,
                    )

                isolate.assert_called_once_with(proxy)
                second_command = run.call_args_list[1].args[0]
                self.assertEqual(second_command[second_command.index("--proxy") + 1], rotated)

    def test_connection_refused_and_permanent_failures_do_not_rotate(self):
        self.assertEqual(retry_runner.classify_failure("Connection refused"), "no_rotate")
        self.assertEqual(retry_runner.classify_failure("This profile is private"), "permanent")
        for kind in ("no_rotate", "permanent"):
            with self.subTest(kind=kind), mock.patch.object(
                retry_runner, "isolated_proxy"
            ) as isolate:
                failure = (1, set(), {"DOWNLOADED": 0, "SKIPPED": 0, "FAILED": 0}, True, kind)
                with mock.patch.dict(os.environ, {
                    "PROFILE_MAX_ATTEMPTS": "1", "RETRY_JITTER": "0"
                }, clear=False), mock.patch.object(retry_runner, "run", return_value=failure):
                    retry_runner.run_profile(
                        "gallery-dl", ["--proxy", "socks5h://u:p@tor:9050"], [],
                        "https://www.tiktok.com/@test", {}, "socks5h://u:p@tor:9050",
                    )
                isolate.assert_not_called()

    def test_exponential_jitter_delay_stays_within_configured_range(self):
        env = {"RETRY_JITTER": "0.25"}
        lower = retry_runner.retry_delay(2, 5, env, lambda low, high: low)
        upper = retry_runner.retry_delay(2, 5, env, lambda low, high: high)
        self.assertEqual(lower, 15)
        self.assertEqual(upper, 25)

    def test_proxy_credentials_are_redacted_from_logs(self):
        value = "failed via socks5h://real-user:real-password@tor:9050"
        redacted = retry_runner.redact_secrets(value)
        self.assertEqual(redacted, "failed via socks5h://***:***@tor:9050")
        self.assertNotIn("real-password", redacted)


class BatchModeTests(unittest.TestCase):
    def test_parse_target_file_ignores_blank_and_comment_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.txt"
            path.write_text(
                "\n# comment\nalice\n@bob\nhttps://www.tiktok.com/@carol\n  # another comment\n",
                encoding="utf-8",
            )
            self.assertEqual(
                retry_runner.read_target_file(path),
                ["alice", "@bob", "https://www.tiktok.com/@carol"],
            )

    def test_missing_and_empty_target_files_raise_clear_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.txt"
            with self.assertRaisesRegex(ValueError, "does not exist"):
                retry_runner.read_target_file(missing)
            empty = Path(directory) / "empty.txt"
            empty.write_text("\n# comments only\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no targets"):
                retry_runner.read_target_file(empty)

    def test_target_file_rejects_ambiguous_or_non_tiktok_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ("--proxy", "https://example.com/@alice", "alice bob"):
                with self.subTest(value=value):
                    path = Path(directory) / "invalid.txt"
                    path.write_text(value + "\n", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "invalid target on line 1"):
                        retry_runner.read_target_file(path)

    def test_batch_aggregates_status_and_returns_nonzero_if_any_target_fails(self):
        results = [
            (0, {"DOWNLOADED": 2, "SKIPPED": 1, "FAILED": 0}, "gallery-dl"),
            (1, {"DOWNLOADED": 0, "SKIPPED": 0, "FAILED": 1}, "yt-dlp"),
        ]
        with mock.patch.object(retry_runner, "execute_target", side_effect=results) as execute, \
                mock.patch("builtins.print") as output:
            rc = retry_runner.run_batch(["alice", "@bob"], ["--range", "1"])

        self.assertEqual(rc, 1)
        self.assertEqual(execute.call_args_list, [
            mock.call("alice", ["--range", "1"], include_unscoped=False),
            mock.call("@bob", ["--range", "1"], include_unscoped=False),
        ])
        summary = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("targets=2", summary)
        self.assertIn("succeeded=1", summary)
        self.assertIn("failed_targets=1", summary)
        self.assertIn("downloaded=2", summary)
        self.assertIn("skipped=1", summary)
        self.assertIn("failed=1", summary)

    def test_single_target_invocation_preserves_target_and_forwards_options(self):
        with mock.patch.object(
            retry_runner, "execute_target",
            return_value=(0, {"DOWNLOADED": 1, "SKIPPED": 0, "FAILED": 0}, "gallery-dl"),
        ) as execute:
            rc = retry_runner.main(["alice", "--range", "1"])

        self.assertEqual(rc, 0)
        execute.assert_called_once_with("alice", ["--range", "1"])

    def test_from_file_alias_forwards_file_targets_and_options(self):
        with mock.patch.object(
            retry_runner, "read_target_file", return_value=["alice", "@bob"]
        ) as read, mock.patch.object(retry_runner, "run_batch", return_value=0) as batch:
            rc = retry_runner.main(["--from-file", "/input/targets.txt", "--range", "2"])

        self.assertEqual(rc, 0)
        read.assert_called_once_with("/input/targets.txt")
        batch.assert_called_once_with(["alice", "@bob"], ["--range", "2"])


class ArchiveHistoryTests(unittest.TestCase):
    def make_archive(self, directory, entries=()):
        path = Path(directory) / "archive.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE archive (entry TEXT PRIMARY KEY) WITHOUT ROWID")
        connection.executemany("INSERT INTO archive(entry) VALUES (?)", ((entry,) for entry in entries))
        connection.commit()
        connection.close()
        return path

    def test_history_list_reports_unique_video_ids_and_record_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.make_archive(directory, (
                "tiktok1234567890123456789_1_",
                "tiktok1234567890123456789_1_file",
                "tiktok9876543210987654321_1_",
            ))
            with mock.patch.object(retry_runner, "ARCHIVE", archive), \
                    mock.patch("builtins.print") as output:
                rc = retry_runner.history_command(["list"])

        self.assertEqual(rc, 0)
        rendered = "\n".join(str(call.args[0]) for call in output.call_args_list)
        self.assertIn("1234567890123456789 records=2", rendered)
        self.assertIn("9876543210987654321 records=1", rendered)

    def test_history_remove_deletes_only_exact_video_id_records(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.make_archive(directory, (
                "tiktok1234567890123456789_1_",
                "tiktok1234567890123456789_2_photo",
                "tiktok1234567890123456780_1_",
            ))
            queue = Path(directory) / "queue.json"
            queue.write_text('{"keep":{"attempts":1}}\n', encoding="utf-8")
            queue_before = queue.read_bytes()
            with mock.patch.object(retry_runner, "ARCHIVE", archive), \
                    mock.patch.object(retry_runner, "QUEUE", queue), \
                    mock.patch("builtins.print") as output:
                rc = retry_runner.history_command(["remove", "1234567890123456789"])
            connection = sqlite3.connect(archive)
            remaining = [row[0] for row in connection.execute("SELECT entry FROM archive")]
            connection.close()
            queue_after = queue.read_bytes()

        self.assertEqual(rc, 0)
        self.assertEqual(remaining, ["tiktok1234567890123456780_1_"])
        self.assertIn("removed 2", output.call_args.args[0])
        self.assertEqual(queue_after, queue_before)

    def test_history_remove_no_match_changes_nothing_and_returns_one(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.make_archive(directory, ("tiktok1234567890123456789_1_",))
            with mock.patch.object(retry_runner, "ARCHIVE", archive):
                rc = retry_runner.history_command(["remove", "9876543210987654321"])
            connection = sqlite3.connect(archive)
            count = connection.execute("SELECT count(*) FROM archive").fetchone()[0]
            connection.close()
        self.assertEqual(rc, 1)
        self.assertEqual(count, 1)

    def test_history_clear_requires_yes_and_then_clears_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.make_archive(directory, (
                "tiktok1234567890123456789_1_", "tiktok9876543210987654321_1_",
            ))
            with mock.patch.object(retry_runner, "ARCHIVE", archive):
                refused = retry_runner.history_command(["clear"])
                connection = sqlite3.connect(archive)
                before = connection.execute("SELECT count(*) FROM archive").fetchone()[0]
                connection.close()
                cleared = retry_runner.history_command(["clear", "--yes"])
                connection = sqlite3.connect(archive)
                after = connection.execute("SELECT count(*) FROM archive").fetchone()[0]
                connection.close()
                archive_preserved = archive.is_file()
        self.assertEqual((refused, before), (2, 2))
        self.assertEqual((cleared, after), (0, 0))
        self.assertTrue(archive_preserved)

    def test_history_missing_archive_and_unexpected_schema_are_clear_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.sqlite3"
            with mock.patch.object(retry_runner, "ARCHIVE", missing), \
                    mock.patch("sys.stderr") as error:
                self.assertEqual(retry_runner.history_command(["list"]), 2)
                self.assertIn("does not exist", "".join(call.args[0] for call in error.write.call_args_list))

            invalid = Path(directory) / "invalid.sqlite3"
            connection = sqlite3.connect(invalid)
            connection.execute("CREATE TABLE wrong (value TEXT)")
            connection.close()
            with mock.patch.object(retry_runner, "ARCHIVE", invalid), \
                    mock.patch("sys.stderr") as error:
                self.assertEqual(retry_runner.history_command(["list"]), 2)
                self.assertIn("unexpected schema", "".join(call.args[0] for call in error.write.call_args_list))

    def test_history_list_empty_archive_is_success_with_clear_message(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.make_archive(directory)
            with mock.patch.object(retry_runner, "ARCHIVE", archive), \
                    mock.patch("builtins.print") as output:
                rc = retry_runner.history_command(["list"])
        self.assertEqual(rc, 0)
        self.assertEqual(output.call_args.args[0], "history: archive is empty")


class ManifestTests(unittest.TestCase):
    def make_store(self, directory):
        return retry_runner.ManifestStore(
            Path(directory) / "tiktok-download-manifest.json",
            Path(directory) / "tiktok-download-manifest.csv",
        )

    def test_downloaded_skipped_and_failed_events_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            store.update("https://www.tiktok.com/@alice", "1111111111", "DOWNLOADED", "/downloads/a.mp4")
            store.update("https://www.tiktok.com/@alice", "2222222222", "SKIPPED", "/downloads/b.mp4")
            store.update("https://www.tiktok.com/@alice", "3333333333", "FAILED", "")
            records = json.loads(store.json_path.read_text(encoding="utf-8"))["records"]
        self.assertEqual([record["status"] for record in records], ["DOWNLOADED", "SKIPPED", "FAILED"])
        self.assertTrue(all(record["updated_at"].endswith("Z") for record in records))

    def test_manifest_deduplicates_by_target_and_id_and_allows_status_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            store.update("https://www.tiktok.com/@alice", "1111111111", "FAILED", "")
            store.update("https://www.tiktok.com/@alice", "1111111111", "DOWNLOADED", "/downloads/final.mp4")
            records = store.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "DOWNLOADED")
        self.assertEqual(records[0]["path"], "/downloads/final.mp4")

    def test_manifest_scopes_same_video_id_by_target(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            store.update("https://www.tiktok.com/@alice", "1111111111", "SKIPPED", "")
            store.update("https://www.tiktok.com/@bob", "1111111111", "FAILED", "")
            records = store.records()
        self.assertEqual([(r["target"], r["status"]) for r in records], [
            ("https://www.tiktok.com/@alice", "SKIPPED"),
            ("https://www.tiktok.com/@bob", "FAILED"),
        ])

    def test_csv_has_same_columns_and_dataset_as_json_with_unicode_path(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            path = "/downloads/Perfil con espacios/猫 video.mp4"
            store.update("https://www.tiktok.com/@alice", "1111111111", "DOWNLOADED", path)
            json_records = json.loads(store.json_path.read_text(encoding="utf-8"))["records"]
            with store.csv_path.open(encoding="utf-8", newline="") as stream:
                csv_records = list(csv.DictReader(stream))
        self.assertEqual(list(csv_records[0]), retry_runner.MANIFEST_COLUMNS)
        self.assertEqual(csv_records, json_records)
        self.assertEqual(csv_records[0]["path"], path)

    def test_corrupt_manifest_fails_safe_without_overwriting_either_file(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            store.json_path.write_text("{broken", encoding="utf-8")
            store.csv_path.write_text("sentinel", encoding="utf-8")
            before_json = store.json_path.read_bytes()
            before_csv = store.csv_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "corrupt manifest"):
                store.update("https://www.tiktok.com/@alice", "1111111111", "FAILED", "")
            self.assertEqual(store.json_path.read_bytes(), before_json)
            self.assertEqual(store.csv_path.read_bytes(), before_csv)

    def test_manifest_contains_no_proxy_cookie_or_raw_error_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            retry_runner.record_status(
                store, "https://www.tiktok.com/@alice", "FAILED", "1111111111", ""
            )
            persisted = store.json_path.read_text(encoding="utf-8")
        for secret in ("socks5h://user:password", "sid_tt", "raw traceback"):
            self.assertNotIn(secret, persisted)

    def test_gallery_status_event_attributes_unicode_path_to_exact_target(self):
        class Process:
            stdout = iter([
                '__TIKTOK_DL_STATUS__ DOWNLOADED "1111111111" '
                '"/downloads/Alice videos/猫.mp4" "post"\n'
            ])

            @staticmethod
            def wait():
                return 0

        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            with mock.patch.object(retry_runner.subprocess, "Popen", return_value=Process()):
                rc, failed, counts, profile_failed, failure_kind = retry_runner.run(
                    ["gallery-dl"], {}, "https://www.tiktok.com/@alice", store
                )
            records = store.records()
        self.assertEqual((rc, failed, profile_failed, failure_kind), (0, set(), False, None))
        self.assertEqual(counts, {"DOWNLOADED": 1, "SKIPPED": 0, "FAILED": 0})
        self.assertEqual(records[0]["target"], "https://www.tiktok.com/@alice")
        self.assertEqual(records[0]["direct_url"], "https://www.tiktok.com/@alice/video/1111111111")
        self.assertEqual(records[0]["path"], "/downloads/Alice videos/猫.mp4")


if __name__ == "__main__":
    unittest.main()
