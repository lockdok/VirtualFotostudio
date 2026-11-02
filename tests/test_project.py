import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import comfy_bridge
from pose_director import PoseConfig, generate_all_pose_prompts
from scripts import concept_settings, download_models, manage_services
from shoot_runner import reroll_tile, run_series
from workflow_builder import build_faceid_workflow, upscaled_size


class WorkflowTests(unittest.TestCase):
    def test_graph_connections_and_optional_detail_pass(self):
        workflow = build_faceid_workflow(
            "positive", "negative", "checkpoint.safetensors", "face.png",
            body_reference_image="body.png", seed=42, hires_scale=1.5,
        )
        self.assertEqual(workflow["14"]["inputs"]["image"], "body.png")
        self.assertEqual(workflow["15"]["inputs"]["preset"], "PLUS FACE (portraits)")
        self.assertEqual(workflow["16"]["inputs"]["image"], ["14", 0])
        self.assertEqual(workflow["3"]["inputs"]["model"], ["16", 0])
        self.assertEqual(workflow["11"]["inputs"]["samples"], ["8", 0])
        self.assertEqual(workflow["9"]["inputs"]["samples"], ["12", 0])
        for node in workflow.values():
            for value in node["inputs"].values():
                if isinstance(value, list) and value and isinstance(value[0], str):
                    if value[0].isdigit():
                        self.assertIn(value[0], workflow)

        single_pass = build_faceid_workflow("p", "n", "model", "face.png", seed=1)
        self.assertNotIn("11", single_pass)
        self.assertEqual(upscaled_size(896, 1152, 1.5), (1344, 1728))

    def test_pose_prompt_alias_and_seeded_session(self):
        config = PoseConfig(seed=17, chaos=0)
        first = generate_all_pose_prompts(
            "Golden Hour Botanical", config, n_tiles=3,
            concept_text="custom concept", session_seed=5,
        )
        second = generate_all_pose_prompts(
            "Golden Hour Botanical", config, n_tiles=3,
            concept_text="custom concept", session_seed=5,
        )
        self.assertEqual(first, second)
        self.assertTrue(all("custom concept" in prompt for prompt, _ in first))


class ConceptSettingsTests(unittest.TestCase):
    def test_custom_names_and_prompts_persist_outside_project_when_configured(self):
        concepts = concept_settings.default_concepts()
        concepts["Golden Hour Botanical"] = {
            "name": "Greenhouse Portraits",
            "prompt": "soft window light",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings" / "concepts.json"
            concept_settings.save_concepts(concepts, path)
            self.assertEqual(concept_settings.load_concepts(path), concepts)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_duplicate_or_empty_concept_names_are_rejected(self):
        concepts = concept_settings.default_concepts()
        concepts["Classic Vogue Studio"]["name"] = "Golden Hour Botanical"
        with self.assertRaisesRegex(ValueError, "unique"):
            concept_settings.validate_concepts(concepts)

        concepts = concept_settings.default_concepts()
        concepts["Golden Hour Botanical"]["name"] = " "
        with self.assertRaisesRegex(ValueError, "empty"):
            concept_settings.validate_concepts(concepts)

    def test_malformed_concept_file_reports_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "concepts.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Could not parse"):
                concept_settings.load_concepts(path)


class ReadinessTests(unittest.TestCase):
    @staticmethod
    def _object_info():
        nodes = {name: {} for name in comfy_bridge.REQUIRED_IDENTITY_NODES}
        nodes.update({
            "IPAdapterModelLoader": {"input": {"required": {
                "ipadapter_file": [[
                    comfy_bridge.FACEID_ADAPTER_FILE,
                    comfy_bridge.PLUS_FACE_ADAPTER_FILE,
                ]]
            }}},
            "LoraLoader": {"input": {"required": {
                "lora_name": [[comfy_bridge.FACEID_LORA_FILE]]
            }}},
            "CLIPVisionLoader": {"input": {"required": {
                "clip_name": [["CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"]]
            }}},
        })
        return nodes

    def test_reports_missing_workflow_node(self):
        with patch.object(comfy_bridge.urllib.request, "urlopen") as urlopen:
            response = urlopen.return_value.__enter__.return_value
            response.read.return_value = json.dumps({}).encode()
            missing = comfy_bridge.get_missing_identity_requirements()
        self.assertEqual(missing, sorted(comfy_bridge.REQUIRED_IDENTITY_NODES))

        nodes = self._object_info()
        del nodes["IPAdapterAdvanced"]
        with patch.object(comfy_bridge.urllib.request, "urlopen") as urlopen:
            response = urlopen.return_value.__enter__.return_value
            response.read.return_value = json.dumps(nodes).encode()
            missing = comfy_bridge.get_missing_identity_requirements()
        self.assertIn("IPAdapterAdvanced", missing)

    def test_accepts_complete_workflow_requirements(self):
        nodes = self._object_info()
        with patch.object(comfy_bridge.urllib.request, "urlopen") as urlopen:
            response = urlopen.return_value.__enter__.return_value
            response.read.return_value = json.dumps(nodes).encode()
            missing = comfy_bridge.get_missing_identity_requirements()
        self.assertEqual(missing, [])

    def test_reports_each_missing_required_model(self):
        nodes = self._object_info()
        nodes["IPAdapterModelLoader"]["input"]["required"]["ipadapter_file"][0].remove(
            comfy_bridge.FACEID_ADAPTER_FILE
        )
        nodes["LoraLoader"]["input"]["required"]["lora_name"][0].clear()
        nodes["CLIPVisionLoader"]["input"]["required"]["clip_name"][0].clear()
        with patch.object(comfy_bridge.urllib.request, "urlopen") as urlopen:
            response = urlopen.return_value.__enter__.return_value
            response.read.return_value = json.dumps(nodes).encode()
            missing = comfy_bridge.get_missing_identity_requirements()
        self.assertEqual(len(missing), 3)


class ShootPersistenceTests(unittest.TestCase):
    def _run_shoot(self, output_dir: Path):
        config = PoseConfig(seed=7, chaos=0)
        with patch("shoot_runner.render_image", side_effect=[b"first image", RuntimeError("GPU error")]):
            return run_series(
                output_dir=output_dir, concept="Test", concept_prompt="test concept",
                reference_name="reference.png", checkpoint="model.safetensors",
                pose_config=config, identity_strength=0.8, aspect="Portrait 3:4",
                count=2, client_id="test",
            )

    def test_manifest_tracks_success_and_failure_incrementally(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            record = self._run_shoot(Path(temp_dir))
            manifest = json.loads((record.folder / "shoot_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(record.status, "completed_with_errors")
            self.assertEqual(manifest["status"], "completed_with_errors")
            self.assertEqual(manifest["settings"]["image_count"], 2)
            self.assertEqual(len(manifest["images"]), 1)
            self.assertEqual(manifest["failures"][0]["error"], "GPU error")
            self.assertTrue((record.folder / manifest["images"][0]["file"]).is_file())
            self.assertFalse(list(record.folder.glob("*.tmp")))

    def test_completed_image_callback_includes_saved_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = []
            with patch("shoot_runner.render_image", return_value=b"saved image"):
                record = run_series(
                    output_dir=Path(temp_dir), concept="Test", concept_prompt="test",
                    reference_name="reference.png", checkpoint="model.safetensors",
                    pose_config=PoseConfig(seed=7), identity_strength=0.8,
                    aspect="Portrait 3:4", count=1, client_id="test",
                    on_image=lambda index, data, entry: completed.append((index, data, entry)),
                )
            index, data, entry = completed[0]
            self.assertEqual(index, 0)
            self.assertEqual(data, b"saved image")
            self.assertTrue(Path(entry["path"]).is_file())
            self.assertNotIn("path", record.images[0])

    def test_reroll_preserves_existing_image_when_seed_filename_collides(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("shoot_runner.render_image", return_value=b"original"):
                record = run_series(
                    output_dir=Path(temp_dir), concept="Test", concept_prompt="test",
                    reference_name="reference.png", checkpoint="model.safetensors",
                    pose_config=PoseConfig(seed=7, chaos=0), identity_strength=0.8,
                    aspect="Portrait 3:4", count=1, client_id="test",
                )
            previous = record.images[0]["file"]
            with patch("shoot_runner.generate_pose_prompt", return_value=("new pose", 7)), \
                 patch("shoot_runner.render_image", return_value=b"rerolled"):
                _, entry = reroll_tile(record, 0, client_id="test")
            self.assertEqual(previous, "01_7.png")
            self.assertEqual(entry["file"], "01_7_2.png")
            self.assertEqual((record.folder / previous).read_bytes(), b"original")
            self.assertEqual((record.folder / entry["file"]).read_bytes(), b"rerolled")
            self.assertEqual(record.superseded[0]["file"], previous)

    def test_interrupted_shoot_keeps_an_in_progress_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            def interrupt(_):
                raise RuntimeError("simulated interruption")

            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                run_series(
                    output_dir=Path(temp_dir), concept="Test", concept_prompt="test",
                    reference_name="reference.png", checkpoint="model.safetensors",
                    pose_config=PoseConfig(seed=7), identity_strength=0.8,
                    aspect="Portrait 3:4", count=1, on_status=interrupt,
                )
            folders = list(Path(temp_dir).iterdir())
            manifest = json.loads((folders[0] / "shoot_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "in_progress")
            self.assertEqual(manifest["settings"]["image_count"], 1)


class DownloaderTests(unittest.TestCase):
    def test_size_validation_replaces_incomplete_files_and_skips_valid_ones(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "model.bin"
            destination.write_bytes(b"bad")

            def fake_download(repo_id, filename, local_dir):
                downloaded = Path(local_dir) / filename
                downloaded.parent.mkdir(parents=True, exist_ok=True)
                downloaded.write_bytes(b"valid")
                return str(downloaded)

            fake_hub = types.SimpleNamespace(hf_hub_download=fake_download)
            with patch.dict(sys.modules, {"huggingface_hub": fake_hub}):
                result = download_models._fetch("repo", "model.bin", destination, "test model", 5)
                self.assertEqual(result.read_bytes(), b"valid")
                with patch.dict(sys.modules, {"huggingface_hub": types.SimpleNamespace(
                    hf_hub_download=unittest.mock.Mock(side_effect=AssertionError("unexpected download"))
                )}):
                    download_models._fetch("repo", "model.bin", destination, "test model", 5)

    def test_bad_download_never_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "model.bin"
            destination.write_bytes(b"existing")

            def fake_download(repo_id, filename, local_dir):
                downloaded = Path(local_dir) / filename
                downloaded.write_bytes(b"short")
                return str(downloaded)

            fake_hub = types.SimpleNamespace(hf_hub_download=fake_download)
            with patch.dict(sys.modules, {"huggingface_hub": fake_hub}):
                with self.assertRaises(RuntimeError):
                    download_models._fetch("repo", "model.bin", destination, "test model", 6)
            self.assertEqual(destination.read_bytes(), b"existing")


class ServiceManagerTests(unittest.TestCase):
    def test_tracked_services_stop_comfy_first_and_photostudio_last(self):
        stopped = []
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(manage_services, "stop_service", side_effect=lambda name, _: stopped.append(name)):
            manage_services.stop_tracked_services(Path(temp_dir))
        self.assertEqual(stopped, ["comfy", "photostudio"])

    @unittest.skipUnless(sys.platform == "win32", "Windows service launch flags are platform-specific.")
    def test_started_services_do_not_create_console_windows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            process = types.SimpleNamespace(pid=1234, poll=lambda: None)
            snapshot = {"creation_time": 123}
            with patch.object(manage_services.subprocess, "Popen", return_value=process) as popen, \
                 patch.object(manage_services, "_process_snapshot", return_value=snapshot), \
                 patch.object(manage_services.time, "sleep"):
                manage_services.start_service(
                    "photostudio", root / "services", root / "logs", root,
                    ["photostudio_app.py"], [sys.executable, "photostudio_app.py"],
                )

        self.assertEqual(
            popen.call_args.kwargs["creationflags"],
            manage_services.subprocess.CREATE_NO_WINDOW
            | manage_services.subprocess.CREATE_NEW_PROCESS_GROUP
            | manage_services.subprocess.BELOW_NORMAL_PRIORITY_CLASS,
        )

    def test_process_record_requires_same_executable_creation_and_command(self):
        record = {
            "executable": sys.executable,
            "creation_time": 123,
            "match": ["photostudio_app.py", "--server.port 7860"],
        }
        snapshot = {
            "executable": sys.executable,
            "creation_time": 123,
            "command_line": f'"{sys.executable}" photostudio_app.py --server.port 7860',
        }
        self.assertTrue(manage_services._record_matches(record, snapshot))
        self.assertFalse(manage_services._record_matches(record, {**snapshot, "creation_time": 456}))
        self.assertFalse(manage_services._record_matches(record, {**snapshot, "command_line": "other process"}))

    def test_untracked_service_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manage_services.stop_service("photostudio", Path(temp_dir))

    @unittest.skipUnless(sys.platform == "win32", "Windows process management is platform-specific.")
    def test_stop_service_terminates_only_the_recorded_process_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_dir = Path(temp_dir)
            record = {
                "pid": 1234,
                "executable": sys.executable,
                "creation_time": 123,
                "match": ["photostudio_app.py"],
            }
            manage_services._record_path(pid_dir, "photostudio").write_text(json.dumps(record))
            snapshot = {
                "executable": sys.executable,
                "creation_time": 123,
                "command_line": f'"{sys.executable}" photostudio_app.py',
            }
            with patch.object(manage_services, "_process_snapshot", return_value=snapshot), \
                 patch.object(manage_services.subprocess, "run") as run:
                manage_services.stop_service("photostudio", pid_dir)

            self.assertIn("VFS_PROCESS_ID", run.call_args.kwargs["env"])
            self.assertEqual(
                run.call_args.kwargs["env"]["VFS_RECORD_PATH"],
                str(manage_services._record_path(pid_dir, "photostudio")),
            )
            self.assertIn("Stop-Process -Id $root.ProcessId", run.call_args.args[0][-1])
            self.assertFalse(manage_services._record_path(pid_dir, "photostudio").exists())

    def test_start_command_arguments_are_parsed_before_the_separator(self):
        arguments = [
            "manage_services.py", "start", "photostudio",
            "--pid-dir", "C:\\services", "--log-dir", "C:\\logs",
            "--cwd", "C:\\project", "--match", "photostudio_app.py",
            "--match", "--server.port 7860", "--", "python.exe", "-m", "streamlit",
        ]
        with patch.object(sys, "argv", arguments), \
             patch.object(manage_services, "start_service") as start:
            manage_services.main()
        start.assert_called_once_with(
            "photostudio", Path("C:\\services"), Path("C:\\logs"), Path("C:\\project"),
            ["photostudio_app.py", "--server.port 7860"],
            ["python.exe", "-m", "streamlit"],
        )


if __name__ == "__main__":
    unittest.main()
