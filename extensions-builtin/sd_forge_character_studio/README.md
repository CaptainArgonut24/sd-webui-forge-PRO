# Character Studio

Create character, style, or background presets in the Character Studio tab. A
reference image is optional. Saving clears the editor; choose a saved preset to
edit it again.

Generate using Forge's normal txt2img screen. Open **Character Studio: References
& Layout**, enable it for the generation, and select presets or mention a saved
character's name in the prompt. Use **Refresh presets** after saving a preset.
When disabled, txt2img behaves normally.

Reference images need a compatible installed IP-Adapter model and image encoder.
They use available ControlNet units; already-enabled units are preserved. Layout
regions are soft guidance and do not guarantee character separation.
Use **Refresh IP-Adapter models** after adding models. Choose an adapter matching
the checkpoint (SD 1.5 or SDXL) and its matching image encoder; the official
SD 1.5 Plus and SDXL Plus ViT-H adapters use **CLIP-ViT-H (IPAdapter)**.

For regional prompts, enable Character Studio, select each character and choose
its region, then select **Hybrid** under Regional separation and turn off
**Use reference images**. This uses the installed Forge Couple extension and
its per-region LoRA handling. Put shared scene details and shared LoRAs in the
main prompt; character preset prompts and LoRAs are assigned to their regions.
Character negative prompts remain global. Named characters not assigned a region
produce an error rather than being silently placed. Attention mode is available
only when character presets contain no LoRAs; it does not isolate LoRAs.

Regional mode currently cannot be combined with IP-Adapter reference images,
Hires. fix, selected txt2img scripts, or Forge Couple's own Enable checkbox.
It requires the compatible Forge Couple extension and a supported model (SD 1.5,
SDXL or Anima). Its regional conditioning is guidance, not a guarantee of
character placement or anatomical accuracy.

Set **Character Studio preset library folder** in Settings > Character Studio to
store presets and optional reference images in another location. On first use
of an empty configured library, the existing Forge library is copied there
without deleting the original. If an old reference image is missing, its preset
is preserved and the editor asks for a replacement.
