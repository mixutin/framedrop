"""Caption formats and offline-transcription transactions, without model downloads.

The real service, project validation, revision history and job files are used.
Only speech-model readiness and subprocess launch are substituted where needed.
"""

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from montage_studio import captions, transcription
from montage_studio.config import Config, StudioError, atomic_json, utcnow
from montage_studio.projects import new_id
from montage_studio.service import Service


def cue(text="A caption", start=.125, end=1.875, ident=None):
    return {"id": ident or new_id("cap"), "start": start, "end": end, "text": text}


def semantic(cues):
    return [(item["start"], item["end"], item["text"]) for item in cues]


class CaptionFormatTests(unittest.TestCase):
    def test_timestamp_roundtrip_at_second_minute_and_hour_boundaries(self):
        for value in (0, .001, 1.001, 59.999, 60, 3599.999, 3600, 14399.999, 14400):
            for format in ("srt", "vtt"):
                with self.subTest(value=value, format=format):
                    self.assertEqual(captions.parse_time(captions.timestamp(value, format)), value)
        self.assertEqual(captions.parse_time("01:02.1"), 62.1)
        self.assertEqual(captions.parse_time("00:01:02,12"), 62.12)
        self.assertEqual(captions.timestamp(59.9996), "00:01:00,000")
        for invalid in ("-00:00:01,000", "00:60:00,000", "00:00:60,000", "00:01", "NaN", "1.0"):
            with self.subTest(invalid=invalid), self.assertRaises(StudioError):
                captions.parse_time(invalid)

    def test_plain_text_markup_entities_unicode_and_multiline_roundtrip(self):
        original = [cue("Later", 60, 61), cue('Press <E> & keep &lt; literal\nÄäni: "hei"', .125, 1.875)]
        expected = semantic(sorted(original, key=lambda item: item["start"]))
        for format in ("srt", "vtt"):
            with self.subTest(format=format):
                exported = captions.export_captions(original, format)
                self.assertIn("&lt;E&gt; &amp; keep &amp;lt; literal", exported)
                self.assertEqual(semantic(captions.parse_captions(exported, format)), expected)

    def test_bom_crlf_and_offsets(self):
        source = "\ufeff1\r\n00:00:01,250 --> 00:00:02,500\r\nFirst line\r\nSecond line\r\n"
        self.assertEqual(semantic(captions.parse_captions(source, offset=-.25)), [(1, 2.25, "First line\nSecond line")])
        original = [cue("First\r\nSecond\rThird")]
        for format in ("srt", "vtt"):
            with self.subTest(format=format):
                self.assertEqual(captions.parse_captions(captions.export_captions(original, format), format)[0]["text"], "First\nSecond\nThird")

    def test_vtt_headers_comments_settings_and_cue_identifiers(self):
        source = (
            "\ufeffWEBVTT\tA caption draft\r\nKind: captions\r\nLanguage: fi\r\n\r\n"
            "NOTE reviewer note\r\nThis is not a caption.\r\n\r\n"
            "STYLE\r\n::cue { color: red; }\r\n\r\n"
            "REGION\r\nid:main\r\n\r\n"
            "NOTEBOOK\r\n00:01.000 --> 00:02.000 align:start position:20%\r\n<v Mikael><b>Hi &amp; bye</b></v>\r\n\r\n"
            "WEBVTT is a valid cue identifier\r\n00:02.500 --> 00:03.500\r\nAnother cue\r\n"
        )
        self.assertEqual(semantic(captions.parse_captions(source, "vtt")), [(1, 2, "Hi & bye"), (2.5, 3.5, "Another cue")])

    def test_vtt_magic_is_a_whole_word_without_timing_arrow(self):
        for header in ("WEBVTTBAD", "WEBVTT0", " WEBVTT", "WEBVTT --> cue", "webvtt"):
            with self.subTest(header=header), self.assertRaises(StudioError):
                captions.parse_captions(header + "\n\n00:01.000 --> 00:02.000\nCaption\n", "vtt")

    def test_invalid_or_collapsed_timestamps_cannot_be_exported(self):
        for start, end in ((2, 1), (1, 1), (1.0004, 1.00049)):
            for format in ("srt", "vtt"):
                with self.subTest(start=start, end=end, format=format), self.assertRaises(StudioError):
                    captions.export_captions([cue(start=start, end=end)], format)

    def test_bad_formats_empty_cues_and_out_of_range_offsets_are_rejected(self):
        for text, format, offset in (
            ("", "srt", 0),
            ("1\n00:00:01,000 --> 00:00:02,000\n<b></b>", "srt", 0),
            ("1\n00:00:01,000 --> 00:00:02,000\nCaption", "srt", -2),
            ("1\n03:59:59,000 --> 04:00:00,000\nCaption", "srt", 1),
            ("ignored", "ass", 0),
        ):
            with self.subTest(text=text, format=format, offset=offset), self.assertRaises(StudioError):
                captions.parse_captions(text, format, offset)


class CaptionServiceCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        media = self.base / "Editing"
        media.mkdir()
        self.config = Config(media, media / "MontageStudio", self.base / "state")
        self.service = Service(self.config)
        self.project = self.service.projects.create("Caption test", width=128, height=72, fps=15)

    def snapshot(self):
        return {str(path.relative_to(self.config.workspace)): path.read_bytes() for path in self.config.workspace.rglob("*.json")}

    def save(self, **changes):
        document = self.service.projects.get(self.project["id"])
        document.update(changes)
        self.project = self.service.projects.save(document, document["revision"])
        return self.project

    def ready(self):
        models = self.base / "models"
        models.mkdir(exist_ok=True)
        snapshot = models / "models--Systran--faster-whisper-base" / "snapshots" / "fixture"
        snapshot.mkdir(parents=True, exist_ok=True)
        for filename in ("model.bin", "config.json", "tokenizer.json"):
            (snapshot / filename).write_bytes(b"Local fixture; model execution is mocked.")
        settings = {"installed": True, "model_ready": True, "model": "base", "python": sys.executable, "download_root": str(models)}
        atomic_json(self.config.state_dir / "transcription.json", settings)
        return settings

    def write_job(self, **changes):
        jid = new_id("job")
        directory = self.service.jobs.directory(jid)
        directory.mkdir()
        job = {"id": jid, "kind": "render", "project_id": self.project["id"], "project_name": self.project["name"],
               "revision": self.project["revision"], "status": "completed", "created_at": utcnow(), "updated_at": utcnow(), "progress": 1}
        job.update(changes)
        atomic_json(directory / "job.json", job)
        atomic_json(directory / "project.json", self.project)
        return job

    def render(self):
        output = self.config.renders_dir / (new_id("preview") + ".mp4")
        output.write_bytes(b"Existing rendered media. The mocked model is never invoked.")
        return self.write_job(output_path=str(output), quality="preview")

    def draft(self, cues=None, **changes):
        values = {"kind": "transcription", "timeline_signature": transcription.timeline_signature(self.project),
                  "result": {"captions": [cue("A speech draft", .375, 1.625)] if cues is None else cues, "draft": True}}
        values.update(changes)
        return self.write_job(**values)


class CaptionProjectTests(CaptionServiceCase):
    def test_invalid_imports_do_not_write_project_or_history(self):
        self.save(captions=[cue("Keep this manual caption")])
        before = self.snapshot()
        for text, format in (
            ("Malformed caption contents", "srt"),
            ("1\n00:00:03,000 --> 00:00:02,000\nBackwards", "srt"),
            ("1\n00:00:01,000 --> 00:00:02,000\n" + "x" * 2001, "srt"),
            ("1\n00:00:01,000 --> 00:00:02,000\nNUL\x00", "srt"),
            ("WEBVTTBAD\n\n00:01.000 --> 00:02.000\nText", "vtt"),
        ):
            with self.subTest(format=format, sample=text[:35]), self.assertRaises(StudioError):
                self.service.call("captions_import", {"project_id": self.project["id"], "expected_revision": self.project["revision"], "text": text, "format": format})
            self.assertEqual(self.snapshot(), before)

    def test_import_append_preserves_manual_text_style_and_revision_history(self):
        manual = cue("Manually corrected <literal> text", 3, 4)
        style = {**captions.DEFAULT_STYLE, "preset": "boxed", "position": "top", "font_size": 64}
        self.save(captions=[manual], caption_style=style)
        revision = self.project["revision"]
        result = self.service.call("captions_import", {"project_id": self.project["id"], "expected_revision": revision,
                                  "text": "1\n00:00:01,250 --> 00:00:02,000\nImported &lt;text&gt;", "replace": False})
        self.assertEqual(result["revision"], revision + 1)
        self.assertEqual(result["caption_style"], style)
        self.assertEqual(result["captions"][1], manual)
        self.assertEqual(semantic(result["captions"]), [(1.25, 2, "Imported <text>"), (3, 4, manual["text"])])
        history = json.loads((self.config.history_dir / self.project["id"] / f"{revision}.json").read_text())
        self.assertEqual(history["captions"], [manual])
        before = self.snapshot()
        with self.assertRaises(StudioError) as caught:
            self.service.call("captions_import", {"project_id": self.project["id"], "expected_revision": revision,
                              "text": "1\n00:00:01,000 --> 00:00:02,000\nStale overwrite"})
        self.assertEqual(caught.exception.code, "revision_conflict")
        self.assertEqual(self.snapshot(), before)

    def test_exports_are_revision_qualified_and_do_not_overwrite_changed_files(self):
        self.save(captions=[cue("Press <E> & go\nAgain")])
        for format in ("srt", "vtt"):
            with self.subTest(format=format):
                arguments = {"project_id": self.project["id"], "format": format}
                result = self.service.call("captions_export", arguments)
                target = Path(result["path"])
                self.assertEqual(target.name, f"{self.project['id']}_r{self.project['revision']}.{format}")
                self.assertEqual(target.read_text(), result["text"])
                self.assertEqual(result["cue_count"], 1)
                self.assertEqual(semantic(captions.parse_captions(result["text"], format)), semantic(self.project["captions"]))
                self.assertEqual(self.service.call("captions_export", arguments), result)
                target.write_text("A user-edited export")
                with self.assertRaises(StudioError):
                    self.service.call("captions_export", arguments)
                self.assertEqual(target.read_text(), "A user-edited export")

    def test_actual_engine_accepts_caption_styles_and_rejects_bad_style_without_save(self):
        for preset, position in (("clean", "bottom"), ("bold", "center"), ("boxed", "top")):
            style = {**captions.DEFAULT_STYLE, "preset": preset, "position": position, "color": "#ffffffcc"}
            self.save(captions=[cue()], caption_style=style)
            self.assertTrue(self.service.call("project_validate", {"project_id": self.project["id"]})["valid"])
        before = self.snapshot()
        for changed in ({"preset": "unknown"}, {"position": "left"}, {"font_size": 2}, {"color": "red"}):
            document = copy.deepcopy(self.project)
            document["caption_style"].update(changed)
            with self.subTest(changed=changed), self.assertRaises(StudioError):
                self.service.projects.save(document, self.project["revision"])
            self.assertEqual(self.snapshot(), before)


class TranscriptionTests(CaptionServiceCase):
    def test_status_checks_local_python_and_model_directory_without_network(self):
        missing = self.service.call("transcription_status", {})
        self.assertFalse(missing["installed"])
        self.assertFalse(missing["model_ready"])
        settings = self.ready()
        self.assertTrue(self.service.call("transcription_status", {})["model_ready"])
        settings["python"] = str(self.base / "missing-python")
        atomic_json(self.config.state_dir / "transcription.json", settings)
        missing = transcription.status(self.config)
        self.assertFalse(missing["installed"])
        self.assertFalse(missing["model_ready"])
        settings["python"] = sys.executable
        settings["download_root"] = str(self.base / "missing-models")
        atomic_json(self.config.state_dir / "transcription.json", settings)
        missing = transcription.status(self.config)
        self.assertTrue(missing["installed"])
        self.assertFalse(missing["model_ready"])

    def test_signature_tracks_timing_inputs_but_allows_manual_caption_edits(self):
        signature = transcription.timeline_signature(self.project)
        visual = copy.deepcopy(self.project)
        visual.update(name="Renamed", revision=8, captions=[cue("Manual")], caption_style={"preset": "boxed"}, titles=[{"text": "Title"}])
        self.assertEqual(transcription.timeline_signature(visual), signature)
        for changes in ({"clips": [{"in": 1, "out": 2}]}, {"audio": [{"start": 2}]},
                        {"canvas": {**self.project["canvas"], "fps": 30}}, {"normalize_audio": False}):
            with self.subTest(changes=changes):
                self.assertNotEqual(transcription.timeline_signature({**self.project, **changes}), signature)

    def test_start_requires_installed_model_and_valid_language_before_creating_job(self):
        with self.assertRaises(StudioError) as caught:
            transcription.start(self.service, self.project["id"], "job_not_present")
        self.assertEqual(caught.exception.code, "transcription_unavailable")
        self.ready()
        for language in ("English", "EN", "en-US", "", "en; exit"):
            with self.subTest(language=language), self.assertRaises(StudioError):
                transcription.start(self.service, self.project["id"], "job_not_present", language)
        self.assertEqual(list(self.config.jobs_dir.iterdir()), [])

    def test_start_rejects_wrong_project_wrong_kind_and_incomplete_render(self):
        self.ready()
        for changes in ({"project_id": "p_other"}, {"kind": "transcription"}, {"status": "failed"}):
            job = self.write_job(**changes)
            before = set(self.config.jobs_dir.iterdir())
            with self.subTest(changes=changes), self.assertRaises(StudioError) as caught:
                transcription.start(self.service, self.project["id"], job["id"])
            self.assertEqual(caught.exception.code, "render_required")
            self.assertEqual(set(self.config.jobs_dir.iterdir()), before)

    def test_start_rejects_stale_preview_and_disappeared_output(self):
        self.ready()
        render = self.render()
        self.save(normalize_audio=False)
        before = set(self.config.jobs_dir.iterdir())
        with self.assertRaises(StudioError) as caught:
            transcription.start(self.service, self.project["id"], render["id"])
        self.assertEqual(caught.exception.code, "preview_outdated")
        fresh = self.render()
        Path(fresh["output_path"]).unlink()
        before = set(self.config.jobs_dir.iterdir())
        with self.assertRaises(StudioError) as caught:
            transcription.start(self.service, self.project["id"], fresh["id"])
        self.assertEqual(caught.exception.code, "output_missing")
        self.assertEqual(set(self.config.jobs_dir.iterdir()), before)

    def test_start_launches_offline_draft_worker_without_modifying_project_or_source(self):
        settings = self.ready()
        render = self.render()
        self.save(captions=[cue("Manual text created after rendering")])
        before = self.snapshot()
        source_before = Path(render["output_path"]).read_bytes()
        with patch.object(transcription.subprocess, "Popen", return_value=SimpleNamespace(pid=os.getpid(), wait=lambda: 0)) as popen:
            result = self.service.call("captions_transcribe", {"project_id": self.project["id"], "render_job_id": render["id"], "language": "fi"})
        self.assertEqual(result["kind"], "transcription")
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["source_render_job_id"], render["id"])
        self.assertEqual(result["revision"], self.project["revision"])
        self.assertEqual(result["timeline_signature"], transcription.timeline_signature(self.project))
        self.assertEqual(result["source_path"], render["output_path"])
        args, kwargs = popen.call_args
        self.assertEqual(args[0][:4], [settings["python"], "-m", "montage_studio", "_transcribe_worker"])
        self.assertEqual(kwargs["env"]["HF_HUB_OFFLINE"], "1")
        self.assertEqual(kwargs["env"]["OMP_NUM_THREADS"], "4")
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(Path(render["output_path"]).read_bytes(), source_before)
        stored = json.loads((self.service.jobs.directory(result["id"]) / "project.json").read_text())
        self.assertEqual(stored, self.project)

    def test_apply_rejects_wrong_project_job_kind_or_stale_timeline(self):
        self.save(captions=[cue("Keep manual")])
        before = self.snapshot()
        for changes in ({"project_id": "p_other"}, {"kind": "render"}, {"status": "failed"}, {"timeline_signature": "outdated"}):
            job = self.draft(**changes)
            with self.subTest(changes=changes), self.assertRaises(StudioError) as caught:
                transcription.apply(self.service, self.project["id"], job["id"], self.project["revision"])
            if "timeline_signature" in changes:
                self.assertEqual(caught.exception.code, "transcript_outdated")
            self.assertEqual(self.snapshot(), before)

    def test_apply_uses_revision_compare_and_swap_and_preserves_manual_when_appending(self):
        manual = cue("Manual original", 3, 4)
        style = {**captions.DEFAULT_STYLE, "preset": "bold"}
        self.save(captions=[manual], caption_style=style)
        draft_cues = [cue("Recognized <literal> speech", .375, 1.625)]
        job = self.draft(draft_cues)
        stale_revision = self.project["revision"]
        manual = {**manual, "text": "Manually corrected after transcription"}
        self.save(captions=[manual])
        before = self.snapshot()
        with self.assertRaises(StudioError) as caught:
            self.service.call("captions_apply", {"project_id": self.project["id"], "job_id": job["id"], "expected_revision": stale_revision})
        self.assertEqual(caught.exception.code, "revision_conflict")
        self.assertEqual(self.snapshot(), before)
        applied = self.service.call("captions_apply", {"project_id": self.project["id"], "job_id": job["id"],
                                   "expected_revision": self.project["revision"], "replace": False})
        self.assertEqual(applied["captions"], draft_cues + [manual])
        self.assertEqual(applied["caption_style"], style)
        self.assertEqual(applied["revision"], self.project["revision"] + 1)
        replaced = transcription.apply(self.service, self.project["id"], job["id"], applied["revision"], replace=True)
        self.assertEqual(replaced["captions"], draft_cues)
        archived = json.loads((self.config.history_dir / self.project["id"] / f"{applied['revision']}.json").read_text())
        self.assertEqual(archived["captions"], draft_cues + [manual])

    def test_empty_transcription_never_clears_existing_manual_captions(self):
        self.save(captions=[cue("A manually authored caption")])
        before = self.snapshot()
        for result in ({"captions": []}, {}):
            job = self.draft(result=result)
            for replace in (True, False):
                with self.subTest(result=result, replace=replace), self.assertRaises(StudioError) as caught:
                    transcription.apply(self.service, self.project["id"], job["id"], self.project["revision"], replace)
                self.assertEqual(caught.exception.code, "no_speech_detected")
                self.assertEqual(self.snapshot(), before)


class TranscriptionCueTests(unittest.TestCase):
    def test_word_grouping_retains_word_boundary_timings_and_plain_text(self):
        words = [SimpleNamespace(word=f" w{index}", start=index*.2, end=(index+1)*.2) for index in range(9)]
        result = transcription.segment_cues(SimpleNamespace(words=words))
        self.assertEqual(semantic(result), [(0, 1.6, "w0 w1 w2 w3 w4 w5 w6 w7"), (1.6, 1.8, "w8")])
        self.assertEqual(len({item["id"] for item in result}), 2)

    def test_fallback_preserves_text_and_clips_negative_start(self):
        segment = SimpleNamespace(text="  Literal <E> & words\nSecond line  ", start=-.01, end=1.12349)
        self.assertEqual(semantic(transcription.segment_cues(segment)), [(0, 1.123, "Literal <E> & words\nSecond line")])

    def test_degenerate_word_and_segment_timings_cannot_create_invalid_cues(self):
        for start, end in ((1.0004, 1.00049), (1, 1.001), (-.02, -.01), (2, 1), (1, 1)):
            with self.subTest(start=start, end=end):
                word = SimpleNamespace(word=" speech", start=start, end=end)
                self.assertEqual(transcription.segment_cues(SimpleNamespace(words=[word])), [])
                self.assertEqual(transcription.segment_cues(SimpleNamespace(words=None, text="speech", start=start, end=end)), [])


if __name__ == "__main__":
    unittest.main()
