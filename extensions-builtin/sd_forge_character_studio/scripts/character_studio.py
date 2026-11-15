import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import gradio as gr
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from modules import script_callbacks, scripts, shared
from modules.paths_internal import data_path, models_path


_CATEGORIES = ("Character", "Style", "Background")
_REGIONS = (
    "Automatic",
    "Left",
    "Center-left",
    "Center",
    "Center-right",
    "Right",
    "Upper left",
    "Upper right",
    "Lower left",
    "Lower right",
)
_ASSET_LOCK = threading.RLock()
_NAME_PATTERN = re.compile(r"[^\w .'-]+", re.UNICODE)
_REGION_SEPARATOR = "|||CHARACTER_STUDIO_REGION|||"
_REGION_BOUNDS = {
    "Left": (0.0, 0.5, 0.0, 1.0),
    "Center-left": (0.0, 0.65, 0.0, 1.0),
    "Center": (0.25, 0.75, 0.0, 1.0),
    "Center-right": (0.35, 1.0, 0.0, 1.0),
    "Right": (0.5, 1.0, 0.0, 1.0),
    "Upper left": (0.0, 0.5, 0.0, 0.5),
    "Upper right": (0.5, 1.0, 0.0, 0.5),
    "Lower left": (0.0, 0.5, 0.5, 1.0),
    "Lower right": (0.5, 1.0, 0.5, 1.0),
}


def _library_paths() -> tuple[Path, Path]:
    configured = shared.opts.data.get("character_studio_library", "")
    directory = Path(configured) if configured else Path(data_path) / "character_studio"
    return directory / "presets.json", directory / "references"


def _image_output_directory() -> Path:
    return Path(shared.opts.outdir_samples or shared.opts.outdir_txt2img_samples)


def open_folder(folder: str) -> str:
    if folder == "models":
        path = Path(models_path)
    elif folder == "stability_matrix":
        configured_path = shared.opts.data.get("character_studio_stability_matrix_models", "")
        if not configured_path:
            raise gr.Error("Enter and save your Stability Matrix models folder first.")
        path = Path(configured_path)
    elif folder == "images":
        path = _image_output_directory()
        path.mkdir(parents=True, exist_ok=True)
    elif folder == "library":
        path = _library_paths()[0].parent
    else:
        raise gr.Error("Unknown folder shortcut.")

    if not path.is_dir():
        raise gr.Error(f"Folder does not exist: {path}")

    try:
        if sys.platform == "win32":
            startfile = getattr(os, "startfile", None)
            if startfile is None:
                raise OSError("Windows folder opener is unavailable.")
            startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as error:
        raise gr.Error(f"Could not open folder {path}: {error}") from error

    return f"Opened folder: {path}"


def save_stability_matrix_folder(folder: str) -> str:
    path = Path((folder or "").strip())
    if not path.is_absolute() or not path.is_dir():
        raise gr.Error("Enter the full path to an existing Stability Matrix models folder.")

    key = "character_studio_stability_matrix_models"
    value = str(path)
    if shared.opts.data.get(key) != value:
        if not shared.opts.set(key, value):
            raise gr.Error("Could not change the folder setting.")
        shared.opts.save(shared.config_filename)
    return f"Saved Stability Matrix models folder: {value}"


def on_ui_settings():
    shared.opts.add_option(
        "character_studio_stability_matrix_models",
        shared.OptionInfo("", "Stability Matrix models folder", section=("character_studio", "Character Studio"), category_id="sd"),
    )
    shared.opts.add_option(
        "character_studio_library",
        shared.OptionInfo("", "Character Studio preset library folder", section=("character_studio", "Character Studio"), category_id="sd").needs_reload_ui(),
    )


def _load_assets() -> list[dict]:
    preset_file, _ = _library_paths()
    legacy_file = Path(data_path) / "character_studio" / "presets.json"
    if preset_file != legacy_file and not preset_file.exists() and legacy_file.is_file():
        _migrate_library(legacy_file, preset_file)
    if not preset_file.exists():
        return []

    return _read_assets(preset_file)


def _read_assets(preset_file: Path) -> list[dict]:
    with _ASSET_LOCK, preset_file.open("r", encoding="utf-8") as file:
        assets = json.load(file)

    if not isinstance(assets, list):
        raise ValueError(f"Character Studio preset file must contain a list: {preset_file}")

    for asset in assets:
        if (
            not isinstance(asset, dict)
            or not isinstance(asset.get("id"), str)
            or not asset["id"]
            or asset.get("category") not in _CATEGORIES
            or not isinstance(asset.get("name"), str)
            or not asset["name"].strip()
            or any(not isinstance(asset.get(field, ""), str) for field in ("prompt", "negative_prompt", "lora_prompt"))
            or (asset.get("reference") is not None and not isinstance(asset.get("reference"), str))
        ):
            raise ValueError(f"Invalid preset entry in {preset_file}")

    return assets


def _migrate_library(source: Path, destination: Path) -> None:
    with _ASSET_LOCK:
        if destination.exists():
            return
        assets = _read_assets(source)
        source_references = (source.parent / "references").resolve()
        destination_references = destination.parent / "references"
        for asset in assets:
            filename = asset.get("reference")
            if not filename:
                continue
            old_path = (source_references / filename).resolve()
            if old_path.parent != source_references:
                raise ValueError(f"Invalid reference path: {filename!r}")
            if not old_path.is_file():
                print(f"Character Studio: reference image is missing for preset {asset['name']!r}; the preset will be preserved.")
                continue
            destination_references.mkdir(parents=True, exist_ok=True)
            new_path = destination_references / filename
            if new_path.exists():
                if not filecmp.cmp(old_path, new_path, shallow=False):
                    raise FileExistsError(f"Cannot migrate reference image because the destination already exists: {new_path}")
                continue
            temporary = new_path.with_name(f"{new_path.name}.{uuid.uuid4().hex}.tmp")
            try:
                shutil.copyfile(old_path, temporary)
                temporary.rename(new_path)
            finally:
                if temporary.exists():
                    temporary.unlink()
        _save_assets(assets)


def _save_assets(assets: list[dict]) -> None:
    preset_file, _ = _library_paths()
    preset_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = preset_file.with_name(f"{preset_file.name}.{uuid.uuid4().hex}.tmp")
    with _ASSET_LOCK:
        try:
            with temporary_file.open("w", encoding="utf-8") as file:
                json.dump(assets, file, ensure_ascii=False, indent=2)
            temporary_file.replace(preset_file)
        finally:
            if temporary_file.exists():
                temporary_file.unlink()


def _find_asset(assets: list[dict], asset_id: str | None) -> dict | None:
    if not asset_id:
        return None
    return next((asset for asset in assets if asset["id"] == asset_id), None)


def _choice_list(assets: list[dict], category: str | None = None) -> list[tuple[str, str]]:
    return [
        (f"{asset['category']} · {asset['name']}", asset["id"])
        for asset in assets
        if category is None or asset["category"] == category
    ]


def _store_reference(reference: Image.Image | None) -> str | None:
    if reference is None:
        return None
    if not isinstance(reference, Image.Image):
        raise gr.Error("The reference image could not be read. Upload it again.")

    _, reference_directory = _library_paths()
    reference_directory.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    reference.convert("RGB").save(reference_directory / filename, format="PNG")
    return filename


def _reference_file(filename: str) -> Path:
    _, reference_directory = _library_paths()
    directory = reference_directory.resolve()
    path = (reference_directory / filename).resolve()
    if path.parent != directory:
        raise ValueError(f"Invalid reference path: {filename!r}")
    return path


def _reference_path(asset: dict) -> Path | None:
    filename = asset.get("reference")
    if not filename:
        return None
    path = _reference_file(filename)
    if not path.is_file():
        raise gr.Error(f"Reference image for {asset['name']!r} is missing. Edit the preset and upload it again.")
    return path


def _load_reference(asset: dict) -> np.ndarray | None:
    path = _reference_path(asset)
    if path is None:
        return None
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB")).copy()


def _asset_key(category: str, name: str) -> tuple[str, str]:
    return category, name.strip().casefold()


def save_preset(category: str, name: str, prompt: str, negative_prompt: str, lora_prompt: str, reference: Image.Image | None, selected_id: str | None):
    name = (name or "").strip()
    if category not in _CATEGORIES:
        raise gr.Error("Choose Character, Style, or Background.")
    if not name or _NAME_PATTERN.search(name):
        raise gr.Error("Enter a preset name using letters, numbers, spaces, dots, apostrophes, or hyphens.")

    assets = _load_assets()
    current = _find_asset(assets, selected_id)
    key = _asset_key(category, name)
    duplicate = next((asset for asset in assets if _asset_key(asset["category"], asset["name"]) == key and asset is not current), None)
    if duplicate:
        raise gr.Error(f"A {category.lower()} preset named {name!r} already exists.")

    previous_reference = current.get("reference") if current else None
    asset = {
        "id": current["id"] if current else uuid.uuid4().hex,
        "category": category,
        "name": name,
        "prompt": (prompt or "").strip(),
        "negative_prompt": (negative_prompt or "").strip(),
        "lora_prompt": (lora_prompt or "").strip(),
        "reference": _store_reference(reference),
    }

    if current:
        assets[assets.index(current)] = asset
    else:
        assets.append(asset)
    _save_assets(assets)

    if previous_reference and previous_reference != asset["reference"]:
        old_reference = _reference_file(previous_reference)
        if old_reference.is_file():
            old_reference.unlink()

    return (
        gr.update(value=None, choices=_choice_list(assets, category)),
        gr.update(value=f"Saved {category.lower()} preset “{name}”."),
        "",
        "",
        "",
        "",
        None,
    )


def delete_preset(selected_id: str | None, category: str):
    assets = _load_assets()
    asset = _find_asset(assets, selected_id)
    if not asset:
        raise gr.Error("Select a preset to delete.")

    assets.remove(asset)
    _save_assets(assets)
    reference = asset.get("reference")
    if reference:
        reference_path = _reference_file(reference)
        if reference_path.is_file():
            reference_path.unlink()

    return (
        gr.update(choices=_choice_list(assets, category), value=None),
        gr.update(value="Preset deleted."),
        "",
        "",
        "",
        "",
        None,
    )


def load_preset(selected_id: str | None):
    asset = _find_asset(_load_assets(), selected_id)
    if not asset:
        return "", "", "", "", None, ""

    reference = None
    status = ""
    path = _reference_file(asset["reference"]) if asset.get("reference") else None
    if path and path.is_file():
        with Image.open(path) as image:
            reference = image.convert("RGB").copy()
    elif path:
        status = "The saved reference image is missing. Upload a replacement or save without an image."
    return asset["name"], asset.get("prompt", ""), asset.get("negative_prompt", ""), asset.get("lora_prompt", ""), reference, status


def _reference_slot_count() -> int:
    return max(1, min(5, int(shared.opts.data.get("control_net_unit_count", 3))))


def _resize_reference_slots(current_count: int, delta: int, max_count: int):
    visible_count = max(1, min(max_count, int(current_count) + delta))
    return (
        visible_count,
        *[gr.update(visible=index < visible_count) for index in range(max_count)],
        *[gr.update(value=None) if index >= visible_count else gr.update() for index in range(max_count)],
        *[gr.update(value="Automatic") if index >= visible_count else gr.update() for index in range(max_count)],
        gr.update(interactive=visible_count < max_count),
        gr.update(interactive=visible_count > 1),
    )


def _region_mask(region: str, width: int, height: int) -> np.ndarray | None:
    if region == "Automatic":
        return None

    rectangles = {
        "Left": (0.02, 0.12, 0.48, 0.96),
        "Center-left": (0.15, 0.08, 0.62, 0.96),
        "Center": (0.25, 0.08, 0.75, 0.96),
        "Center-right": (0.38, 0.08, 0.85, 0.96),
        "Right": (0.52, 0.12, 0.98, 0.96),
        "Upper left": (0.02, 0.02, 0.52, 0.62),
        "Upper right": (0.48, 0.02, 0.98, 0.62),
        "Lower left": (0.02, 0.38, 0.52, 0.98),
        "Lower right": (0.48, 0.38, 0.98, 0.98),
    }
    bounds = rectangles.get(region)
    if bounds is None:
        raise gr.Error(f"Unsupported layout region: {region}")

    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    left, top, right, bottom = bounds
    draw.rounded_rectangle(
        (int(left * width), int(top * height), int(right * width), int(bottom * height)),
        radius=max(1, min(width, height) // 20),
        fill=255,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(1, min(width, height) // 32)))
    return np.asarray(mask)


def _expand_presets(prompt: str, negative_prompt: str, assets: list[dict]) -> tuple[str, str]:
    prompt_parts = [prompt.strip()] if prompt.strip() else []
    negative_parts = [negative_prompt.strip()] if negative_prompt.strip() else []
    selected_characters = [asset for asset in assets if asset["category"] == "Character"]
    character_names = {asset["name"].casefold() for asset in selected_characters}

    for asset in selected_characters:
        name = asset["name"]
        details = asset.get("prompt", "").strip()
        if not details:
            continue
        pattern = re.compile(rf"(?<![\w]){re.escape(name)}(?![\w])", re.IGNORECASE)
        if pattern.search(prompt):
            prompt = pattern.sub(lambda match: f"{match.group(0)}, {details}", prompt, count=1)
            prompt_parts[0] = prompt
        else:
            prompt_parts.append(details)

    for asset in assets:
        if asset["category"] != "Character" or asset["name"].casefold() not in character_names:
            style_prompt = asset.get("prompt", "").strip()
            if style_prompt:
                prompt_parts.append(style_prompt)
        asset_negative = asset.get("negative_prompt", "").strip()
        if asset_negative:
            negative_parts.append(asset_negative)
        lora_prompt = asset.get("lora_prompt", "").strip()
        if lora_prompt:
            prompt_parts.append(lora_prompt)

    return ", ".join(part for part in prompt_parts if part), ", ".join(part for part in negative_parts if part)


def _make_control_units(assets: list[dict], regions: list[str], model: str, preprocessor: str, weight: float, width: int, height: int):
    referenced_assets = []
    for asset, region in zip(assets, regions):
        reference = _load_reference(asset)
        if reference is not None:
            referenced_assets.append((asset, region, reference))

    if not referenced_assets:
        return []
    if not model or model == "None":
        raise gr.Error("Choose an installed IP-Adapter model to use reference images.")
    if not preprocessor or preprocessor == "None":
        raise gr.Error("Choose an IP-Adapter image encoder to use reference images.")

    try:
        from lib_controlnet.external_code import ControlNetUnit
    except ImportError as error:
        raise gr.Error("Reference conditioning requires the built-in ControlNet extension.") from error

    units = []
    for asset, region, reference in referenced_assets:
        mask = _region_mask(region, width, height) if asset["category"] == "Character" else None
        units.append(
            ControlNetUnit(
                enabled=True,
                module=preprocessor,
                model=model,
                weight=float(weight),
                image=reference,
                mask_image=mask,
            )
        )
    return units


def _regional_generation(p, assets: list[dict], regions: list[str], method: str, script_args: list):
    characters = [(asset, region) for asset, region in zip(assets, regions) if asset["category"] == "Character"]
    if not characters or any(region not in _REGION_BOUNDS for _, region in characters):
        raise gr.Error("Select each character preset and choose a specific region for it.")
    if method == "Attention" and any(asset.get("lora_prompt", "").strip() for asset, _ in characters):
        raise gr.Error("Attention mode cannot isolate character LoRAs. Use Hybrid mode instead.")
    if getattr(p, "enable_hr", False):
        raise gr.Error("Regional Character Studio does not support Hires. fix yet; turn it off for this generation.")
    if script_args and script_args[0] not in (0, None):
        raise gr.Error("Regional Character Studio cannot be combined with a selected txt2img script. Set Script to None.")

    controlnet = next((script for script in p.scripts.alwayson_scripts if script.title() == "ControlNet"), None)
    if controlnet is not None:
        for unit in script_args[controlnet.args_from:controlnet.args_to]:
            enabled = unit.get("enabled", False) if isinstance(unit, dict) else getattr(unit, "enabled", False)
            model = unit.get("model", "") if isinstance(unit, dict) else getattr(unit, "model", "")
            module = unit.get("module", "") if isinstance(unit, dict) else getattr(unit, "module", "")
            if enabled and any(token in str(value).lower() for value in (model, module) for token in ("ipadapter", "ip-adapter", "ip_adapter")):
                raise gr.Error("Disable IP-Adapter units in ControlNet before using regional Character Studio.")

    couple = next((script for script in p.scripts.alwayson_scripts if script.title() == "Forge Couple"), None)
    if couple is None:
        raise gr.Error("Regional generation requires the enabled sd-forge-couple-ex extension. Install or enable it and restart Forge.")
    start, end = couple.args_from, couple.args_to
    expected_labels = [
        "Enable", "Compatibility", "Region Assignment", "Couple Separator", "Tile Direction",
        "Global Effect", "Global Effect Weight", None, "Syntax", "Debug", "Include Definitions in Prompt",
        "Separation Method",
    ]
    controls = getattr(couple, "controls", None)
    if end > len(script_args) or not controls or len(controls) < len(expected_labels) or any(
        label is not None and getattr(control, "label", None) != label
        for control, label in zip(controls, expected_labels)
    ):
        raise gr.Error("The installed Forge Couple controls are incompatible. Update Forge Couple and reload the UI.")
    if script_args[start]:
        raise gr.Error("Turn off Forge Couple's own Enable checkbox when using Character Studio regional mode.")
    if _REGION_SEPARATOR in p.prompt:
        raise gr.Error("The prompt contains Character Studio's reserved region separator.")

    common = p.prompt
    for asset, _ in sorted(characters, key=lambda item: len(item[0]["name"]), reverse=True):
        name = re.escape(asset["name"])
        common = re.sub(
            rf"(?<![\w]){name}(?![\w])(?:\s+on\s+the\s+(?:left|right))?",
            "",
            common,
            flags=re.IGNORECASE,
        )
    common = re.sub(r"\s+", " ", common).strip(" ,.")
    global_assets = [asset for asset in assets if asset["category"] != "Character"]
    common, negative = _expand_presets(common, p.negative_prompt or "", global_assets)
    negatives = [negative]
    for asset, _ in characters:
        if asset.get("negative_prompt", "").strip():
            negatives.append(asset["negative_prompt"].strip())
    negative = ", ".join(part for part in negatives if part)
    prompts = [common or "background"]
    mappings = [[0.0, 1.0, 0.0, 1.0, 0.3]]
    for asset, region in characters:
        prompts.append(", ".join(part for part in (common, asset["name"], asset.get("prompt", "").strip(), asset.get("lora_prompt", "").strip()) if part))
        mappings.append([*_REGION_BOUNDS[region], 1.0])

    styles = getattr(p, "styles", None) or []
    if styles:
        prompts = [shared.prompt_styles.apply_styles_to_prompt(prompt, styles) for prompt in prompts]
        negative = shared.prompt_styles.apply_negative_styles_to_prompt(negative, styles)
    couple_args = list(script_args[start:end])
    couple_args[0] = True
    couple_args[1] = True
    couple_args[2] = "Advanced"
    couple_args[3] = _REGION_SEPARATOR
    couple_args[7] = mappings
    couple_args[8] = "off"
    couple_args[11] = method
    script_args[start:end] = couple_args
    return _REGION_SEPARATOR.join(prompts), negative


def _prepare_generation(p, enabled: bool, slot_count: int, *reference_inputs):
    if not enabled:
        return
    if not isinstance(p.prompt, str) or not isinstance(p.negative_prompt, str):
        raise gr.Error("Character Studio requires a single prompt and negative prompt.")

    selected_assets = reference_inputs[:slot_count]
    regions = reference_inputs[slot_count : 2 * slot_count]
    ipadapter_model, preprocessor, reference_strength, use_images, regional_method = reference_inputs[2 * slot_count :]

    assets_all = _load_assets()
    assets = []
    selected_regions = []
    selected_ids = set()
    for asset_id, region in zip(selected_assets, regions):
        if not asset_id:
            continue
        asset = _find_asset(assets_all, asset_id)
        if asset is None:
            raise gr.Error("A selected preset no longer exists. Refresh the page and select it again.")
        if asset["id"] in selected_ids:
            raise gr.Error(f"Preset {asset['name']!r} is selected more than once.")
        assets.append(asset)
        selected_regions.append(region)
        selected_ids.add(asset["id"])

    for asset in sorted(
        (item for item in assets_all if item["category"] == "Character" and item["id"] not in selected_ids),
        key=lambda item: len(item["name"]),
        reverse=True,
    ):
        pattern = re.compile(rf"(?<![\w]){re.escape(asset['name'])}(?![\w])", re.IGNORECASE)
        if pattern.search(p.prompt or ""):
            assets.append(asset)
            selected_regions.append("Automatic")
            selected_ids.add(asset["id"])

    script_args = list(p.script_args)
    if regional_method != "Off":
        if regional_method not in ("Hybrid", "Attention"):
            raise gr.Error("Unsupported regional separation mode.")
        if use_images and any(asset.get("reference") for asset in assets):
            raise gr.Error("Turn off 'Use reference images' for regional generation; IP-Adapter conflicts with Forge Couple.")
        expanded_prompt, expanded_negative = _regional_generation(p, assets, selected_regions, regional_method, script_args)
        p.script_args = tuple(script_args)
        p.prompt, p.negative_prompt = expanded_prompt, expanded_negative
        p.styles = []
        return

    expanded_prompt, expanded_negative = _expand_presets(p.prompt or "", p.negative_prompt or "", assets)
    reference_units = _make_control_units(assets, selected_regions, ipadapter_model, preprocessor, reference_strength, int(p.width), int(p.height)) if use_images else []

    if reference_units:
        controlnet = next((script for script in p.scripts.alwayson_scripts if script.title() == "ControlNet"), None)
        if controlnet is None:
            raise gr.Error("Reference conditioning requires the built-in ControlNet extension.")
        if controlnet.args_to > len(script_args):
            raise gr.Error("ControlNet controls are not initialized. Reload the UI and try again.")
        available = [
            index for index in range(controlnet.args_from, controlnet.args_to)
            if not (script_args[index].get("enabled", False) if isinstance(script_args[index], dict) else getattr(script_args[index], "enabled", False))
        ]
        if len(reference_units) > len(available):
            raise gr.Error("Not enough unused ControlNet units for the selected reference images. Disable other units or increase the unit count in Settings.")
        for index, unit in zip(available, reference_units):
            script_args[index] = unit
        p.script_args = tuple(script_args)
    p.prompt = expanded_prompt
    p.negative_prompt = expanded_negative


def _ipadapter_model_choices():
    from lib_controlnet import global_state

    return [
        name for name in global_state.get_all_controlnet_names()
        if any(token in name.lower() for token in ("ipadapter", "ip-adapter", "ip_adapter"))
    ]


def _refresh_ipadapter_models(selected: str | None):
    from lib_controlnet import global_state

    global_state.update_controlnet_filenames()
    choices = _ipadapter_model_choices()
    value = selected if selected in choices else (choices[0] if selected is None and choices else None)
    if selected and selected not in choices:
        message = f"Found {len(choices)} IP-Adapter models; the previous selection is no longer available."
    else:
        message = f"Found {len(choices)} IP-Adapter models."
    return gr.update(choices=choices, value=value), message


class CharacterStudioScript(scripts.Script):
    propagate_setup_errors = True
    sorting_priority = 11

    def title(self):
        return "Character Studio References & Layout"

    def show(self, is_img2img):
        return False if is_img2img else scripts.AlwaysVisible

    def ui(self, is_img2img):
        from lib_controlnet import global_state

        self.slot_count = _reference_slot_count()
        initial_count = min(3, self.slot_count)
        choices = _choice_list(_load_assets())
        models = _ipadapter_model_choices()
        preprocessors = [name for name in global_state.get_all_preprocessor_names() if "ipadapter" in name.lower() and "insightface" not in name.lower()]
        default_preprocessor = "CLIP-ViT-H (IPAdapter)" if "CLIP-ViT-H (IPAdapter)" in preprocessors else (preprocessors[0] if preprocessors else None)

        with gr.Accordion("Character Studio: References & Layout", open=False):
            enabled = gr.Checkbox(label="Enable Character Studio for this generation", value=False)
            gr.Markdown(
                f"Select presets or use a saved character name in the prompt. Images are optional. "
                f"Up to {self.slot_count} image references share the configured ControlNet units; "
                "regions are soft guidance and do not guarantee separation."
            )
            regional_method = gr.Dropdown(
                label="Regional separation",
                choices=["Off", "Hybrid", "Attention"],
                value="Off",
                info="Hybrid uses Forge Couple for per-character LoRAs. Attention cannot isolate character LoRAs. Turn off reference images for regional generation.",
            )
            use_images = gr.Checkbox(label="Use reference images", value=True)
            count = gr.State(initial_count)
            rows, references, regions = [], [], []
            for index in range(self.slot_count):
                with gr.Row(visible=index < initial_count, elem_classes=["character-studio-reference"]) as row:
                    rows.append(row)
                    references.append(gr.Dropdown(label=f"Reference {index + 1}", choices=choices, value=None, scale=3))
                    regions.append(gr.Dropdown(label="Region", choices=list(_REGIONS), value="Automatic", scale=2))
            with gr.Row():
                add_button = gr.Button("Add reference", interactive=initial_count < self.slot_count)
                remove_button = gr.Button("Remove last", interactive=initial_count > 1)
                refresh_button = gr.Button("Refresh presets")
            model = gr.Dropdown(label="IP-Adapter model", choices=models, value=models[0] if models else None, info="Required only for presets with a reference image.")
            self.model_dropdown = model
            with gr.Row():
                refresh_models = gr.Button("Refresh IP-Adapter models")
                model_status = gr.Markdown()
            preprocessor = gr.Dropdown(label="Image encoder", choices=preprocessors, value=default_preprocessor)
            weight = gr.Slider(label="Reference strength", minimum=0, maximum=2, step=0.05, value=0.8)

            resize_outputs = [count, *rows, *references, *regions, add_button, remove_button]
            add_button.click(fn=lambda current: _resize_reference_slots(current, 1, self.slot_count), inputs=[count], outputs=resize_outputs, show_progress=False)
            remove_button.click(fn=lambda current: _resize_reference_slots(current, -1, self.slot_count), inputs=[count], outputs=resize_outputs, show_progress=False)
            refresh_button.click(
                fn=lambda: [gr.update(choices=_choice_list(_load_assets())) for _ in references],
                outputs=references,
                show_progress=False,
            )
            refresh_models.click(fn=_refresh_ipadapter_models, inputs=[model], outputs=[model, model_status], show_progress=False)

        return [enabled, *references, *regions, model, preprocessor, weight, use_images, regional_method]

    def setup(self, p, enabled, *reference_inputs):
        _prepare_generation(p, enabled, self.slot_count, *reference_inputs)


def create_ui():
    assets = _load_assets()
    editor_choices = _choice_list(assets, "Character")
    runner = getattr(scripts, "scripts_txt2img", None)
    studio_script = next(
        (script for script in getattr(runner, "alwayson_scripts", [])
         if isinstance(script, CharacterStudioScript) and getattr(script, "model_dropdown", None) is not None
         and "txt2img" not in getattr(shared.opts, "hidden_tabs", [])),
        None,
    )

    with gr.Blocks(elem_id="character_studio", elem_classes=["character-studio"]) as interface:
        gr.Markdown("## Character Studio\nSave reusable character, style, and background presets for txt2img.")

        with gr.Tabs():
            with gr.Tab("Create & manage presets"):
                with gr.Row():
                    with gr.Column(scale=1):
                        category = gr.Dropdown(label="Preset type", choices=list(_CATEGORIES), value="Character")
                        editor_dropdown = gr.Dropdown(label="Saved presets", choices=editor_choices, value=None, allow_custom_value=False)
                        name = gr.Textbox(label="Preset name", placeholder="Makucha")
                        default_prompt = gr.Textbox(label="Default prompt details", lines=4, placeholder="male, anthro, leopard, green eyes, yellow sclera")
                        default_negative = gr.Textbox(label="Default negative prompt", lines=2)
                        lora_prompt = gr.Textbox(label="LoRA prompt tokens", placeholder="<lora:MakuchaILITR2:1>")
                        reference_image = gr.Image(label="Reference image (optional)", type="pil", image_mode="RGB", sources="upload", height=280)
                        with gr.Row():
                            save_button = gr.Button("Save preset", variant="primary")
                            delete_button = gr.Button("Delete preset", variant="secondary")
                        refresh_editor_models = gr.Button("Refresh IP-Adapter models")
                    with gr.Column(scale=1):
                        gr.Markdown(
                            "### How presets work\n"
                            "- Reference images are optional. To use one, select an IP-Adapter model in txt2img.\n"
                            "- Enable Character Studio in txt2img and write a saved character's name in your prompt.\n"
                            "- LoRA tokens are added to the prompt automatically.\n"
                            "- Select style and background presets in References & Layout.\n"
                            "- After saving, the editor clears so you can create another preset. Refresh presets in txt2img to see new selections."
                        )
                status = gr.Markdown()

            with gr.Tab("Folders"):
                gr.Markdown("Folder shortcuts open on the computer hosting Forge. Set the preset library folder in Settings > Character Studio.")
                refresh_folder_models = gr.Button("Refresh IP-Adapter models")
                with gr.Row():
                    library_directory = gr.Textbox(label="Character Studio preset library", value=str(_library_paths()[0].parent), interactive=False, scale=5)
                    copy_library_button = gr.Button("Copy path", scale=1)
                    open_library_button = gr.Button("Open", scale=1)
                with gr.Row():
                    matrix_directory = gr.Textbox(label="Stability Matrix models folder", value=shared.opts.data.get("character_studio_stability_matrix_models", ""), placeholder=r"D:\StabilityMatrix\Models", scale=5)
                    save_matrix_button = gr.Button("Save path", scale=1)
                    copy_matrix_button = gr.Button("Copy path", scale=1)
                    open_matrix_button = gr.Button("Open", scale=1)
                with gr.Row():
                    model_directory = gr.Textbox(label="Forge models folder", value=str(models_path), interactive=False, elem_id="character_studio_models_path", scale=5)
                    copy_models_button = gr.Button("Copy path", scale=1)
                    open_models_button = gr.Button("Open", scale=1)
                with gr.Row():
                    images_directory = gr.Textbox(label="Generated images folder", value=str(_image_output_directory()), interactive=False, elem_id="character_studio_images_path", scale=5)
                    copy_images_button = gr.Button("Copy path", scale=1)
                    open_images_button = gr.Button("Open", scale=1)
                folder_status = gr.Markdown()

        def bind_model_refresh(button, output_status):
            if studio_script is None:
                def refresh_without_dropdown():
                    _, message = _refresh_ipadapter_models(None)
                    return message + " The txt2img reference controls are unavailable."

                button.click(fn=refresh_without_dropdown, outputs=[output_status], show_progress=False)
            else:
                dropdown = studio_script.model_dropdown
                button.click(fn=_refresh_ipadapter_models, inputs=[dropdown], outputs=[dropdown, output_status], show_progress=False)

        bind_model_refresh(refresh_editor_models, status)
        bind_model_refresh(refresh_folder_models, folder_status)

        copy_path_js = (
            "async function(path){"
            "try{await navigator.clipboard.writeText(path);return['Copied path to clipboard.'];}"
            "catch(error){return['Could not copy path: '+String(error)];}"
            "}"
        )
        copy_models_button.click(
            fn=None,
            inputs=[model_directory],
            outputs=[folder_status],
            js=copy_path_js,
            show_progress=False,
        )
        copy_images_button.click(
            fn=None,
            inputs=[images_directory],
            outputs=[folder_status],
            js=copy_path_js,
            show_progress=False,
        )
        copy_matrix_button.click(
            fn=None,
            inputs=[matrix_directory],
            outputs=[folder_status],
            js=copy_path_js,
            show_progress=False,
        )
        copy_library_button.click(
            fn=None,
            inputs=[library_directory],
            outputs=[folder_status],
            js=copy_path_js,
            show_progress=False,
        )
        save_matrix_button.click(fn=save_stability_matrix_folder, inputs=[matrix_directory], outputs=[folder_status], show_progress=False)
        open_library_button.click(fn=lambda: open_folder("library"), outputs=[folder_status], show_progress=False)
        open_matrix_button.click(fn=lambda: open_folder("stability_matrix"), outputs=[folder_status], show_progress=False)
        open_models_button.click(fn=lambda: open_folder("models"), outputs=[folder_status], show_progress=False)
        open_images_button.click(fn=lambda: open_folder("images"), outputs=[folder_status], show_progress=False)

        def change_category(selected_category: str):
            return (
                gr.update(choices=_choice_list(_load_assets(), selected_category), value=None),
                "",
                "",
                "",
                "",
                None,
            )

        category.change(
            fn=change_category,
            inputs=[category],
            outputs=[editor_dropdown, name, default_prompt, default_negative, lora_prompt, reference_image],
            show_progress=False,
        )
        editor_dropdown.change(
            fn=load_preset,
            inputs=[editor_dropdown],
            outputs=[name, default_prompt, default_negative, lora_prompt, reference_image, status],
            show_progress=False,
        )

        save_button.click(
            fn=save_preset,
            inputs=[category, name, default_prompt, default_negative, lora_prompt, reference_image, editor_dropdown],
            outputs=[editor_dropdown, status, name, default_prompt, default_negative, lora_prompt, reference_image],
            show_progress=False,
        )
        delete_button.click(
            fn=delete_preset,
            inputs=[editor_dropdown, category],
            outputs=[editor_dropdown, status, name, default_prompt, default_negative, lora_prompt, reference_image],
            show_progress=False,
        )

    return [(interface, "Character Studio", "character_studio")]


script_callbacks.on_ui_settings(on_ui_settings)
script_callbacks.on_ui_tabs(create_ui)
