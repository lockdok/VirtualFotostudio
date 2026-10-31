"""ComfyUI workflow builders used by Virtual AI Photostudio.

The identity workflow deliberately keeps the person in the uploaded reference
image separate from the styling prompt.  It uses the locally installed
``ComfyUI_IPAdapter_plus`` FaceID Plus V2 nodes; no training or remote image
processing is involved.
"""

import uuid
from typing import Optional


def build_txt2img_workflow(
    positive_prompt: str,
    negative_prompt: str,
    checkpoint_name: str,
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 7.0,
    sampler: str = "dpmpp_2m_sde",
    scheduler: str = "karras",
    seed: int = -1,
) -> dict:
    """
    Build a standard SDXL text-to-image ComfyUI workflow.
    Returns a dict representing the node graph.
    """
    import random
    if seed < 0:
        seed = random.randint(0, 2**31 - 1)

    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint_name}
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": positive_prompt,
                "clip": ["1", 1]
            }
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": negative_prompt,
                "clip": ["1", 1]
            }
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1}
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            }
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]}
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "photostudio",
                "images": ["6", 0]
            }
        },
    }


def build_faceid_workflow(
    positive_prompt: str,
    negative_prompt: str,
    checkpoint_name: str,
    reference_image: str,
    width: int = 768,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 6.5,
    sampler: str = "dpmpp_2m_sde",
    scheduler: str = "karras",
    seed: int = -1,
    identity_strength: float = 0.85,
    output_prefix: str = "photostudio",
) -> dict:
    """Build an SDXL + IP-Adapter FaceID Plus V2 workflow.

    ``identity_strength`` controls both FaceID V2 conditioning and its paired
    LoRA.  The values are intentionally clamped to conservative ranges: the
    prompt must still be able to control wardrobe, composition and lighting.
    """
    import random

    if seed < 0:
        seed = random.randint(0, 2**31 - 1)
    strength = max(0.25, min(float(identity_strength), 1.25))
    lora_strength = max(0.25, min(strength * 0.72, 0.9))

    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint_name},
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": reference_image},
        },
        "3": {
            "class_type": "IPAdapterUnifiedLoaderFaceID",
            "inputs": {
                "model": ["1", 0],
                "preset": "FACEID PLUS V2",
                "lora_strength": lora_strength,
                "provider": "CUDA",
            },
        },
        "4": {
            "class_type": "IPAdapterFaceID",
            "inputs": {
                "model": ["3", 0],
                "ipadapter": ["3", 1],
                "image": ["2", 0],
                "weight": strength,
                "weight_faceidv2": max(0.5, min(strength * 1.6, 2.0)),
                "weight_type": "linear",
                "combine_embeds": "average",
                "start_at": 0.0,
                "end_at": 1.0,
                "embeds_scaling": "V only",
            },
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": ["1", 1]},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]},
        },
        "7": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["7", 0],
            },
        },
        "9": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["8", 0], "vae": ["1", 2]},
        },
        "10": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": output_prefix, "images": ["9", 0]},
        },
    }


def build_test_workflow(checkpoint_name: str) -> dict:
    """Minimal test workflow to verify ComfyUI is responding."""
    return build_txt2img_workflow(
        positive_prompt="a beautiful red apple on a white table, studio photography",
        negative_prompt="cartoon, blurry, low quality",
        checkpoint_name=checkpoint_name,
        width=512,
        height=512,
        steps=5,
        seed=42,
    )

