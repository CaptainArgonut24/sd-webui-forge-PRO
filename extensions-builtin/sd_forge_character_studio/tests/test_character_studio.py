import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import gradio as gr
from PIL import Image


class ControlNetUnit:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class CharacterStudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.shared = types.SimpleNamespace(
            opts=types.SimpleNamespace(data={"control_net_unit_count": 3}, outdir_samples="", outdir_txt2img_samples=str(cls.root)),
        )
        modules = types.ModuleType("modules")
        modules.script_callbacks = types.SimpleNamespace(on_ui_settings=lambda fn: None, on_ui_tabs=lambda fn: None)
        modules.scripts = types.SimpleNamespace(Script=object, AlwaysVisible=object())
        modules.shared = cls.shared
        paths = types.ModuleType("modules.paths_internal")
        paths.data_path = str(cls.root)
        paths.models_path = str(cls.root / "models")
        controlnet = types.ModuleType("lib_controlnet")
        cls.global_state = types.SimpleNamespace(
            get_all_controlnet_names=lambda: [],
            get_all_preprocessor_names=lambda: [],
            update_controlnet_filenames=lambda: None,
        )
        controlnet.global_state = cls.global_state
        external = types.ModuleType("lib_controlnet.external_code")
        external.ControlNetUnit = ControlNetUnit
        cls.modules_patch = mock.patch.dict(sys.modules, {
            "modules": modules,
            "modules.paths_internal": paths,
            "lib_controlnet": controlnet,
            "lib_controlnet.external_code": external,
        })
        cls.modules_patch.start()
        path = Path(__file__).resolve().parents[1] / "scripts" / "character_studio.py"
        spec = importlib.util.spec_from_file_location("character_studio_test_module", path)
        cls.studio = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.studio)

    @classmethod
    def tearDownClass(cls):
        cls.modules_patch.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.library = self.root / self.id().rsplit(".", 1)[-1]
        self.studio.data_path = str(self.root / (self.id().rsplit(".", 1)[-1] + "-legacy"))
        self.shared.opts.data["character_studio_library"] = str(self.library)

    def test_preset_without_image_clears_and_expands_only_when_enabled(self):
        result = self.studio.save_preset("Character", "Makucha", "leopard", "", "<lora:makucha:1>", None, None)
        self.assertEqual(result[2:], ("", "", "", "", None))
        assets = self.studio._load_assets()
        self.assertIsNone(assets[0]["reference"])
        p = types.SimpleNamespace(prompt="Makucha hugging", negative_prompt="", width=512, height=512, script_args=(0,))
        self.studio._prepare_generation(p, False, 3)
        self.assertEqual(p.prompt, "Makucha hugging")
        self.studio._prepare_generation(p, True, 3, *([None] * 3), *(["Automatic"] * 3), None, None, 0.8, True, "Off")
        self.assertIn("leopard", p.prompt)
        self.assertIn("<lora:makucha:1>", p.prompt)

    def test_reference_preserves_other_controlnet_units_and_fails_when_full(self):
        image = Image.new("RGB", (4, 4))
        self.studio.save_preset("Character", "Kovu", "lion", "", "", image, None)
        asset = self.studio._load_assets()[0]
        existing = ControlNetUnit(enabled=True)
        control = types.SimpleNamespace(title=lambda: "ControlNet", args_from=1, args_to=3)
        p = types.SimpleNamespace(
            prompt="Kovu", negative_prompt="", width=64, height=64,
            script_args=(0, existing, ControlNetUnit(enabled=False)),
            scripts=types.SimpleNamespace(alwayson_scripts=[control]),
        )
        inputs = (asset["id"], None, None, "Left", "Automatic", "Automatic", "ipadapter", "encoder", 0.8, True, "Off")
        self.studio._prepare_generation(p, True, 3, *inputs)
        self.assertIs(p.script_args[1], existing)
        self.assertTrue(p.script_args[2].enabled)
        self.assertIsNotNone(p.script_args[2].mask_image)
        p.prompt = "Kovu"
        with self.assertRaises(gr.Error):
            self.studio._prepare_generation(p, True, 3, *inputs)

    def test_edit_preset_can_remove_optional_image(self):
        image = Image.new("RGB", (4, 4))
        self.studio.save_preset("Character", "Kovu", "lion", "", "", image, None)
        asset = self.studio._load_assets()[0]
        reference = self.library / "references" / asset["reference"]
        self.studio.save_preset("Character", "Kovu", "lion", "", "", None, asset["id"])
        self.assertIsNone(self.studio._load_assets()[0]["reference"])
        self.assertFalse(reference.exists())

    def test_legacy_migration_preserves_missing_image_and_original(self):
        legacy = Path(self.studio.data_path) / "character_studio"
        references = legacy / "references"
        references.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (2, 2)).save(references / "present.png")
        records = [
            {"id": "1", "category": "Character", "name": "One", "reference": "present.png"},
            {"id": "2", "category": "Character", "name": "Two", "reference": "missing.png"},
        ]
        (legacy / "presets.json").write_text(json.dumps(records), encoding="utf-8")
        self.assertEqual(self.studio._load_assets(), records)
        self.assertTrue((references / "present.png").exists())
        self.assertTrue((self.library / "references" / "present.png").exists())
        self.assertIn("missing", self.studio.load_preset("2")[-1])

    def test_ui_construction(self):
        with gr.Blocks():
            controls = self.studio.CharacterStudioScript().ui(False)
        self.assertEqual(len(controls), 12)
        self.assertEqual(self.studio.create_ui()[0][1], "Character Studio")

    def test_refresh_rescans_models_and_preserves_or_clears_selection(self):
        names = []

        def rescan():
            names[:] = ["controlnet", "ip-adapter-plus_sd15", "ip-adapter-plus_sdxl_vit-h"]

        with mock.patch.object(self.global_state, "update_controlnet_filenames", side_effect=rescan) as refresh:
            with mock.patch.object(self.global_state, "get_all_controlnet_names", side_effect=lambda: names):
                update, message = self.studio._refresh_ipadapter_models("ip-adapter-plus_sd15")
                self.assertEqual(update["choices"], names[1:])
                self.assertEqual(update["value"], "ip-adapter-plus_sd15")
                self.assertIn("2", message)
                update, message = self.studio._refresh_ipadapter_models("removed-model")
                self.assertIsNone(update["value"])
                self.assertIn("no longer available", message)
                update, _ = self.studio._refresh_ipadapter_models(None)
                self.assertEqual(update["value"], names[1])
                self.assertEqual(refresh.call_count, 3)

    def test_refresh_buttons_target_txt2img_model_dropdown(self):
        script = self.studio.CharacterStudioScript()
        with gr.Blocks() as generation:
            script.ui(False)
        runner = types.SimpleNamespace(alwayson_scripts=[script])
        with mock.patch.object(self.studio.scripts, "scripts_txt2img", runner, create=True):
            editor = self.studio.create_ui()[0][0]
        with gr.Blocks() as combined:
            generation.render()
            editor.render()
        dropdown_id = script.model_dropdown._id
        refresh_events = [
            dependency for dependency in combined.config["dependencies"]
            if dependency.get("outputs") and dependency["outputs"][0] == dropdown_id
        ]
        self.assertEqual(len(refresh_events), 3)

    def test_hidden_txt2img_does_not_leave_dangling_refresh_outputs(self):
        script = self.studio.CharacterStudioScript()
        with gr.Blocks():
            script.ui(False)
        runner = types.SimpleNamespace(alwayson_scripts=[script])
        with mock.patch.object(self.studio.scripts, "scripts_txt2img", runner, create=True):
            with mock.patch.object(self.shared.opts, "hidden_tabs", ["txt2img"], create=True):
                editor = self.studio.create_ui()[0][0]
        for dependency in editor.config["dependencies"]:
            self.assertNotIn(script.model_dropdown._id, dependency["outputs"])

    def test_regional_hybrid_routes_characters_and_loras_to_regions(self):
        studio = self.studio
        assets = [
            {"id": "m", "category": "Character", "name": "Makucha", "prompt": "leopard", "lora_prompt": "<lora:makucha:1>", "reference": None},
            {"id": "c", "category": "Character", "name": "Chuluun", "prompt": "snow leopard", "lora_prompt": "<lora:chuluun:1>", "reference": None},
        ]
        labels = ["Enable", "Compatibility", "Region Assignment", "Couple Separator", "Tile Direction", "Global Effect",
                  "Global Effect Weight", None, "Syntax", "Debug", "Include Definitions in Prompt", "Separation Method"]
        controls = [types.SimpleNamespace(label=label) for label in labels]
        couple = types.SimpleNamespace(title=lambda: "Forge Couple", args_from=1, args_to=13, controls=controls)
        p = types.SimpleNamespace(prompt="snow, Chuluun on the left. Makucha on the right, <lora:style:1>",
                                  negative_prompt="", width=512, height=512, styles=[],
                                  script_args=(0, False, True, "Basic", "", "Horizontal", "None", 0.5, [], "{ }", False, True, "Attention"),
                                  scripts=types.SimpleNamespace(alwayson_scripts=[couple]))
        inputs = ("m", "c", None, "Right", "Left", "Automatic", None, None, 0.8, False, "Hybrid")
        with mock.patch.object(studio, "_load_assets", return_value=assets):
            studio._prepare_generation(p, True, 3, *inputs)
        background, right, left = p.prompt.split(studio._REGION_SEPARATOR)
        self.assertNotIn("Makucha", background)
        self.assertNotIn("Chuluun", background)
        self.assertIn("<lora:style:1>", background)
        self.assertIn("<lora:style:1>", right)
        self.assertIn("<lora:makucha:1>", right)
        self.assertNotIn("<lora:chuluun:1>", right)
        self.assertIn("<lora:chuluun:1>", left)
        self.assertNotIn("<lora:makucha:1>", left)
        self.assertEqual(p.script_args[8][1], [0.5, 1.0, 0.0, 1.0, 1.0])
        self.assertEqual(p.script_args[8][2], [0.0, 0.5, 0.0, 1.0, 1.0])
        self.assertEqual(p.script_args[12], "Hybrid")

    def test_regional_mode_rejects_missing_regions_and_image_conflicts(self):
        asset = {"id": "m", "category": "Character", "name": "Makucha", "prompt": "", "lora_prompt": "<lora:m:1>", "reference": "image.png"}
        p = types.SimpleNamespace(prompt="Makucha", negative_prompt="", width=512, height=512, script_args=(0,),
                                  scripts=types.SimpleNamespace(alwayson_scripts=[]))
        with mock.patch.object(self.studio, "_load_assets", return_value=[asset]):
            with self.assertRaisesRegex(gr.Error, "Turn off"):
                self.studio._prepare_generation(p, True, 1, "m", "Right", None, None, 0.8, True, "Hybrid")
            with self.assertRaisesRegex(gr.Error, "specific region"):
                self.studio._prepare_generation(p, True, 1, "m", "Automatic", None, None, 0.8, False, "Hybrid")
            with self.assertRaisesRegex(gr.Error, "cannot isolate"):
                self.studio._prepare_generation(p, True, 1, "m", "Right", None, None, 0.8, False, "Attention")
            with self.assertRaisesRegex(gr.Error, "requires"):
                self.studio._prepare_generation(p, True, 1, "m", "Right", None, None, 0.8, False, "Hybrid")

    def test_regional_mode_rejects_existing_ipadapter_controlnet(self):
        asset = {"id": "m", "category": "Character", "name": "Makucha", "reference": None}
        control = types.SimpleNamespace(title=lambda: "ControlNet", args_from=1, args_to=2)
        p = types.SimpleNamespace(
            prompt="Makucha", negative_prompt="", script_args=(0, ControlNetUnit(enabled=True, model="ip-adapter", module="encoder")),
            scripts=types.SimpleNamespace(alwayson_scripts=[control]),
        )
        with mock.patch.object(self.studio, "_load_assets", return_value=[asset]):
            with self.assertRaisesRegex(gr.Error, "Disable IP-Adapter"):
                self.studio._prepare_generation(p, True, 1, "m", "Right", None, None, 0.8, False, "Hybrid")


if __name__ == "__main__":
    unittest.main()
