"""Inference for the two published FUSED checkpoints.

Architecture: Nuzhdin et al., https://arxiv.org/abs/2608.28302.
The forensic encoder follows Su et al., https://github.com/scu-zjz/SparseViT
(CC BY 4.0). This inference-only adaptation uses tensor operations and omits
training, stochastic depth and unused prediction heads.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np  # type: ignore[import-not-found]
import torch  # type: ignore[import-not-found]
from PIL import Image
from torch import Tensor
from torch.nn import functional as F  # type: ignore[import-not-found]

from image_analysis.cure import digest

WEIGHTS = {
    "fused_opensdi.pth": (
        "7e527d49080a773641cf96915b4b3fa12d571c5b87f35c527f13ab82f148364c"
    ),
    "fused_sofake.pth": (
        "0f9273ba9d48b1a6de0d2b602c7a26cdd3624967f465ff0683668ef9c4359ad3"
    ),
    "open_clip_pytorch_model.bin": (
        "d571d992c3fc1d9d6f771ad4eb0ae4cb63745d3bd0cf3363ecde5ff249e2f155"
    ),
}


def tokens(image: Tensor) -> Tensor:
    return image.flatten(2).transpose(1, 2)


def grid(sequence: Tensor, side: int) -> Tensor:
    return sequence.transpose(1, 2).reshape(sequence.size(0), -1, side, side)


def resize(x: Tensor, size: int) -> Tensor:
    return F.interpolate(x, size=(size, size), mode="bilinear", align_corners=False)


def attend(q: Tensor, k: Tensor, v: Tensor, heads: int) -> Tensor:
    batch, length, width = q.shape
    head_width = width // heads
    q = q.reshape(batch, length, heads, head_width).transpose(1, 2)
    k = k.reshape(batch, -1, heads, head_width).transpose(1, 2)
    v = v.reshape(batch, -1, heads, head_width).transpose(1, 2)
    attention = ((q @ k.transpose(-1, -2)) * head_width**-0.5).softmax(dim=-1)
    return (attention @ v).transpose(1, 2).reshape(batch, length, width)


class Checkpoint:
    def __init__(self, state: dict[str, Tensor]) -> None:
        self.w = state

    def conv(self, x: Tensor, key: str, stride: int = 1, groups: int = 1) -> Tensor:
        weight = self.w[key + ".weight"]
        padding = weight.size(-1) // 2 if stride == 1 else 0
        return F.conv2d(
            x, weight, self.w.get(key + ".bias"), stride, padding, groups=groups
        )

    def linear(self, x: Tensor, key: str) -> Tensor:
        return F.linear(x, self.w[key + ".weight"], self.w.get(key + ".bias"))

    def norm(self, x: Tensor, key: str, eps: float = 1e-5) -> Tensor:
        return F.layer_norm(
            x, (x.size(-1),), self.w[key + ".weight"], self.w[key + ".bias"], eps
        )

    def batch_norm(self, x: Tensor, key: str) -> Tensor:
        return F.batch_norm(
            x,
            self.w[key + ".running_mean"],
            self.w[key + ".running_var"],
            self.w[key + ".weight"],
            self.w[key + ".bias"],
        )

    def conv_block(self, x: Tensor, key: str) -> Tensor:
        x = x + self.conv(x, key + ".pos_embed", groups=x.size(1))
        local = self.conv(self.batch_norm(x, key + ".norm1"), key + ".conv1")
        local = self.conv(local, key + ".attn", groups=x.size(1))
        x = x + self.conv(local, key + ".conv2")
        hidden = self.conv(self.batch_norm(x, key + ".norm2"), key + ".mlp.fc1")
        return x + self.conv(F.gelu(hidden), key + ".mlp.fc2")

    def sparse_block(self, x: Tensor, key: str, stride: int) -> Tensor:
        batch, width, side, _ = x.shape
        group_side = side // stride
        # Gather tokens whose row and column share the same residue modulo stride.
        groups = x.reshape(batch, width, group_side, stride, group_side, stride)
        groups = groups.permute(0, 3, 5, 2, 4, 1).reshape(-1, group_side**2, width)
        qkv = self.linear(self.norm(groups, key + ".norm1", 1e-6), key + ".attn.qkv")
        query, key_tokens, values = qkv.chunk(3, dim=-1)
        delta = self.linear(
            attend(query, key_tokens, values, width // 64), key + ".attn.proj"
        )
        delta = delta.reshape(batch, stride, stride, group_side, group_side, width)
        delta = delta.permute(0, 3, 1, 4, 2, 5).reshape(batch, side**2, width)
        sequence = tokens(x) + self.w[key + ".gamma_1"] * delta
        hidden = self.linear(
            self.norm(sequence, key + ".norm2", 1e-6), key + ".mlp.fc1"
        )
        hidden = self.conv(
            grid(hidden, side), key + ".mlp.dwconv.dwconv", groups=hidden.size(-1)
        )
        delta = self.linear(F.gelu(tokens(hidden)), key + ".mlp.fc2")
        return grid(sequence + self.w[key + ".gamma_2"] * delta, side)

    def forensic_map(self, x: Tensor) -> Tensor:
        features = []
        for stage, depth in enumerate((5, 8, 20, 7), start=1):
            stem = f"encoder.patch_embed{stage}"
            x = self.conv(x, stem + ".proj", stride=4 if stage == 1 else 2)
            x = grid(self.norm(tokens(x), stem + ".norm"), x.size(-1))
            for index in range(depth):
                key = f"encoder.blocks{stage}.{index}"
                if stage < 3:
                    x = self.conv_block(x, key)
                elif stage == 3:
                    x = self.sparse_block(x, key, (8, 4, 2, 1)[index // 5])
                    if index in (4, 9, 14):
                        features.append(x)
                else:
                    x = self.sparse_block(x, key, (2, 1)[index // 4])
                    if index == 3:
                        features.append(x)
            if stage >= 3:
                features.append(
                    grid(self.norm(tokens(x), f"encoder.norm{stage}", 1e-6), x.size(-1))
                )
        sides = features[0].size(-1)
        projected = [
            self.conv(x, f"lmu.conv_layer{i}") if i <= 4 else resize(x, sides)
            for i, x in enumerate(features, start=1)
        ]
        combined = sum(
            self.w[f"lmu.gamma{i}"] * tokens(x)
            for i, x in enumerate(projected, start=1)
        )
        return grid(self.norm(combined, "lmu.norm", 1e-6), sides)

    def pool(self, x: Tensor, key: str) -> Tensor:
        latents = self.w[key + ".latents"].expand(x.size(0), -1, -1)
        weight = self.w[key + ".mha.in_proj_weight"].chunk(3)
        bias = self.w[key + ".mha.in_proj_bias"].chunk(3)
        q, k, v = [F.linear(t, w, b) for t, w, b in zip((latents, x, x), weight, bias)]
        output = self.linear(attend(q, k, v, 8), key + ".mha.out_proj")
        return self.linear(self.norm(output, key + ".norm"), key + ".out_proj")

    def swiglu(self, x: Tensor, key: str) -> Tensor:
        value, gate = self.linear(x, key + ".fc").chunk(2, dim=-1)
        return self.linear(F.silu(gate) * value, key + ".proj")

    def experts(self, x: Tensor) -> Tensor:
        flat = x.flatten(0, 1)
        p = self.linear(flat, "moe_ffn.router").softmax(dim=-1)
        weights, indices = p.topk(2, dim=-1)
        weights = weights / weights.sum(dim=-1, keepdim=True)
        result = torch.zeros_like(flat)
        for expert in range(8):
            rows, slots = torch.where(indices == expert)
            predicted = self.swiglu(flat[rows], f"moe_ffn.experts.{expert}.ffn")
            result.index_add_(0, rows, weights[rows, slots, None] * predicted)
        return result.reshape_as(x)

    def fused_attention(self, x: Tensor) -> Tensor:
        key = "self_attn"
        q, k, v = self.linear(self.norm(x, key + ".norm"), key + ".qkv").chunk(
            3, dim=-1
        )
        q = self.norm(q, key + ".q_norm")
        k = self.norm(k, key + ".k_norm")
        return self.linear(attend(q, k, v, 8), key + ".out_proj")

    def predict(self, image: Tensor, semantic: Tensor) -> tuple[Tensor, Tensor]:
        forensic = self.forensic_map(image)
        forensic_tokens = self.pool(tokens(forensic), "svit_pooling")
        semantic_tokens = tokens(self.conv(semantic, "convnext_proj"))
        stream = torch.cat((forensic_tokens, semantic_tokens), dim=1)
        mixture = self.experts(self.norm(stream, "concat_norm2"))
        stream = self.norm(stream + mixture, "post_moe_norm")
        attention = self.fused_attention(stream)
        stream = self.norm(stream + attention, "pre_pool_norm")
        pooled = self.pool(stream, "final_attn_pool")
        logits = self.linear(self.swiglu(pooled[:, 0], "head.0"), "head.1")
        context = grid(stream[:, forensic_tokens.size(1) :], semantic.size(-1))
        dense = torch.cat((forensic, resize(context, forensic.size(-1))), dim=1)
        for conv, norm in ((0, 1), (3, 4)):
            dense = self.conv(dense, f"joint_seg_decoder.{conv}")
            key = f"joint_seg_decoder.{norm}"
            dense = F.gelu(
                F.group_norm(dense, 32, self.w[key + ".weight"], self.w[key + ".bias"])
            )
        local = self.conv(dense, "joint_seg_decoder.6")
        return logits, resize(local, 512)


class FusedEnsemble:
    def __init__(self, directory: Path, device: str) -> None:
        import timm  # type: ignore[import-not-found]
        from torchvision import transforms  # type: ignore[import-not-found]

        self.device = torch.device(device)
        for name, expected in WEIGHTS.items():
            if digest(directory / name) != expected:
                raise ValueError(f"Unexpected FUSED artifact: {name}")

        backbone = timm.create_model(
            "convnext_xxlarge.clip_laion2b_soup",
            pretrained=False,
            num_classes=0,
        )
        state = torch.load(
            directory / "open_clip_pytorch_model.bin",
            map_location="cpu",
            weights_only=True,
        )
        prefix = "visual.trunk."
        if any(k.startswith(prefix) for k in state):
            state = {
                k[len(prefix) :]: v for k, v in state.items() if k.startswith(prefix)
            }
        expected_keys = set(backbone.state_dict())
        backbone.load_state_dict(
            {k: v for k, v in state.items() if k in expected_keys}, strict=True
        )
        del state
        self.backbone = backbone.eval().to(self.device)
        self.models = []
        for name in tuple(WEIGHTS)[:2]:
            payload = torch.load(
                directory / name, map_location="cpu", weights_only=True
            )
            self.models.append(
                Checkpoint(
                    {k: v.to(self.device) for k, v in payload["state_dict"].items()}
                )
            )
        self.transform = transforms.Compose(
            [
                transforms.Resize((512, 512)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )
        self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.device).view(
            1, 3, 1, 1
        )
        self.std = torch.tensor([0.229, 0.224, 0.225], device=self.device).view(
            1, 3, 1, 1
        )

    def predict(self, image: Image.Image) -> list[tuple[float, np.ndarray]]:
        with torch.inference_mode():
            return self._predict(image)

    def _predict(self, image: Image.Image) -> list[tuple[float, np.ndarray]]:
        x = self.transform(image).unsqueeze(0).to(self.device)
        stats = self.models[0].w
        clip_input = (
            x * (self.std / stats["clip_std"])
            + (self.mean - stats["clip_mean"]) / stats["clip_std"]
        )
        semantic = self.backbone.forward_features(clip_input)
        outputs = []
        for model in self.models:
            logits, mask = model.predict(x, semantic)
            if not torch.isfinite(logits).all() or not torch.isfinite(mask).all():
                raise RuntimeError("Non-finite FUSED output")
            outputs.append(
                (
                    logits.float().softmax(dim=-1)[0, 1].item(),
                    mask.float().sigmoid()[0, 0].cpu().numpy(),
                )
            )
        return outputs
