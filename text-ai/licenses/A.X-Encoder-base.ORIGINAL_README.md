---
license: apache-2.0
license_link: https://huggingface.co/skt/A.X-3.1/blob/main/LICENSE
language:
- en
- ko
pipeline_tag: text-classification
library_name: transformers
model_id: skt/A.X-Encoder-base
developers: SKT AI Model Lab
model-index:
- name: A.X-Encoder-base
  results:
  - task:
      type: text-classification
      name: kobest
    metrics:
    - type: KoBEST
      value: 85.50
  - task:
      type: text-classification
      name: klue
    metrics:
    - type: KLUE
      value: 86.10
---

# A.X Encoder

<div align="center">
  <img src="./assets/A.X_from_scratch_logo_ko_4x3.png" alt="A.X Logo" width="300"/>
</div>

## A.X Encoder Highlights

**A.X Encoder** (pronounced "A dot X") is SKT's document understanding model optimized for Korean-language understanding and enterprise deployment.
This lightweight encoder was developed entirely in-house by SKT, encompassing model architecture, data curation, and training, all carried out on SKT’s proprietary supercomputing infrastructure, TITAN. 
This model utilizes the ModernBERT architecture, which supports flash attention and long-context processing.

- **Longer Context**: A.X Encoder supports long-context processing of up to **16,384** tokens.
- **Faster Inference**: A.X Encoder achieves up to 3x faster inference speed than earlier models.
- **Superior Korean Language Understanding**: A.X Encoder achieves superior performance on diverse Korean NLU tasks.


## Core Technologies

A.X Encoder represents **an efficient long document understanding model** for processing a large-scale corpus, developed end-to-end by SKT.

This model plays a key role in **data curation for A.X LLM** by serving as a versatile document classifier, identifying features such as educational value, domain category, and difficulty level.

## Benchmark Results

### Model Inference Speed (Run on an A100 GPU)
<div align="center">
  <img src="./assets/speed.png" alt="inference" width="500"/>
</div>

### Model Performance
<div align="center">
  <img src="./assets/performance.png" alt="performance" width="500"/>
</div>

| Method                        | BoolQ (f1) | COPA (f1) | Sentineg (f1) | WiC (f1) | **Avg. (KoBEST)** |
| ----------------------------- | ---------- | --------- | ------------- | -------- | ----------------- |
| **klue/roberta-base**         | 72.04      | 65.14     | 90.39         | 78.19    | 76.44             |
| **kakaobank/kf-deberta-base** | 81.30      | 76.50     | 94.70         | 80.50    | 83.25             |
| **skt/A.X-Encoder-base**      | 84.50      | 78.70     | 96.00         | 80.80    | **85.50**             |


| Method                        | NLI (acc) | STS (f1) | YNAT (acc) | **Avg. (KLUE)** |
| ----------------------------- | --------- | -------- | ---------- | --------------- |
| **klue/roberta-base**         | 84.53     | 84.57    | 86.48      | 85.19           |
| **kakaobank/kf-deberta-base** | 86.10     | 84.30    | 87.00      | 85.80           |
| **skt/A.X-Encoder-base**      | 87.00     | 84.80    | 86.50      | **86.10**           |


## 🚀 Quickstart

### with HuggingFace Transformers

- `transformers>=4.51.0` or the latest version is required to use `skt/A.X-Encoder-base`
```bash
pip install transformers>=4.51.0
```

⚠️ If your GPU supports it, we recommend using A.X Encoder with Flash Attention 2 to reach the highest efficiency. To do so, install Flash Attention as follows, then use the model as normal:

```bash
pip install flash-attn --no-build-isolation
```
#### Example Usage

Using AutoModelForMaskedLM:

```python
import torch
from transformers import AutoTokenizer, AutoModelForMaskedLM

model_id = "skt/A.X-Encoder-base"
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForMaskedLM.from_pretrained(model_id, attn_implementation="flash_attention_2", torch_dtype=torch.bfloat16)

text = "한국의 수도는 <mask>."
inputs = tokenizer(text, return_tensors="pt")
outputs = model(**inputs)

# To get predictions for the mask:
masked_index = inputs["input_ids"][0].tolist().index(tokenizer.mask_token_id)
predicted_token_id = outputs.logits[0, masked_index].argmax(axis=-1)
predicted_token = tokenizer.decode(predicted_token_id)
print("Predicted token:", predicted_token)
# Predicted token: 서울
```

Using a pipeline:

```python
import torch
from transformers import pipeline
from pprint import pprint

pipe = pipeline(
    "fill-mask",
    model="skt/A.X-Encoder-base",
    torch_dtype=torch.bfloat16,
)

input_text = "한국의 수도는 <mask>."
results = pipe(input_text)
pprint(results)
# [{'score': 0.07568359375,
#  'sequence': '한국의 수도는 서울.',
#  'token': 31430,
#  'token_str': '서울'}, ...
```

## License

The `A.X Encoder` model is licensed under `Apache License 2.0`.

## Citation
```
@article{SKTAdotXEncoder-base,
  title={A.X Encoder-base},
  author={SKT AI Model Lab},
  year={2025},
  url={https://huggingface.co/skt/A.X-Encoder-base}
}
```

## Contact

- Business & Partnership Contact: [a.x@sk.com](a.x@sk.com)