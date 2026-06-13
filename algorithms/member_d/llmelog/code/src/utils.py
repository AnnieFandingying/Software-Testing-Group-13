import os
import sys
import numpy as np
import pandas as pd
import re
import json
from tqdm import tqdm
from collections import OrderedDict
import re

DEFAULT_BERT_MODEL_ID = "google-bert/bert-base-uncased"


def load_json(fp):
    if not os.path.exists(fp):
        return dict()

    with open(fp, 'r', encoding='utf8') as f:
        return json.load(f)

def get_main_dir():
    if hasattr(sys, 'frozen'):
        return os.path.join(os.path.dirname(sys.executable))
    return os.path.join(os.path.dirname(__file__), '..')

def get_abs_path(*name):
    return os.path.abspath(os.path.join(get_main_dir(), *name))


def ensure_local_bert_model(local_dir="bert-base-en", model_id=DEFAULT_BERT_MODEL_ID):
    """Download the base BERT encoder if the local model weights are missing."""
    model_dir = get_abs_path(local_dir)
    weight_path = os.path.join(model_dir, "pytorch_model.bin")
    safetensors_path = os.path.join(model_dir, "model.safetensors")
    config_path = os.path.join(model_dir, "config.json")
    vocab_path = os.path.join(model_dir, "vocab.txt")

    has_weights = os.path.exists(weight_path) or os.path.exists(safetensors_path)
    if has_weights and os.path.exists(config_path) and os.path.exists(vocab_path):
        return model_dir

    os.makedirs(model_dir, exist_ok=True)
    print(f"Local BERT weights not found in {model_dir}. Downloading {model_id} ...")

    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModel.from_pretrained(model_id)
    tokenizer.save_pretrained(model_dir)
    model.save_pretrained(model_dir)

    print(f"Saved base BERT model to {model_dir}")
    return model_dir

