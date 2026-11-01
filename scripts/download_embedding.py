"""僅安裝階段下載模型；日常檢索只讀取本地權重。"""
from pathlib import Path
import os

os.environ['HF_HUB_OFFLINE'] = '0'
os.environ['TRANSFORMERS_OFFLINE'] = '0'
from huggingface_hub import snapshot_download

if __name__ == '__main__':
    destination = Path(__file__).resolve().parent.parent / '.models' / 'bge-small-zh-v1.5'
    snapshot_download('BAAI/bge-small-zh-v1.5', local_dir=str(destination),
        allow_patterns=['config.json', 'model.safetensors', 'modules.json', 'sentence_bert_config.json',
                        'config_sentence_transformers.json', '1_Pooling/*', 'tokenizer.json',
                        'tokenizer_config.json', 'special_tokens_map.json', 'vocab.txt', 'README.md'])
    print(f'模型已下載至 {destination}')
