# INFERENCE ONLY, NO GROUND TRUTHS
#%%
import argparse
from datasets import Dataset, DatasetDict
import importlib
import numpy as np
import os
import pickle
from torch.utils.data import DataLoader
from tqdm import tqdm
from prompts.prompt import descriptors
from utils.grpo_utils import init_prompt_builder, load_sampling_params
from recipes import MODELS
from grpo import get_prompt_modules, get_var, SYSTEM_PROMPT

# Load and prep dataset
def load_sle_data(files):
    print('Building prompts...')
    from grpo import build_prompt
    data = []
    for file in files:
        for descrip in descriptors:
            print(file, descrip)
            prompt = build_prompt(source_dir, file, descrip, prompt_builder, False, args.v2_prompt)
            # truncate prompt
            prompt = prompt[:max_seq_length]
            datapoint = {
                "filename": file,
                "prompt": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "answer": {
                    "descriptor": descrip,
                }
            }
            data.append(datapoint)
    return data

def collate_fn(batch):
    batch_prompt = [item["prompt"] for item in batch]
    return {"prompt": batch_prompt}

def inference(dataset):
    sampling_params = load_sampling_params(args.model_name)
    batch_size = 16
    dataloader = DataLoader(
        dataset, batch_size=batch_size, shuffle=False, collate_fn=collate_fn
    )
    results, results_logprobs, results_perplexities, results_entropies = [], [], [], []
    if os.path.exists(f'temp_{args.n_run}'):
        with open(f'temp_{args.n_run}', 'rb') as fin:
            res = pickle.load(fin)
        results = res['results_full']
        print(len(results))
    count = 0
    for batch in tqdm(dataloader):
        if count < len(results)//batch_size:
            count += 1
            continue
        prompts = tokenizer.apply_chat_template(
            batch["prompt"], tokenize=False, add_generation_prompt=True
        )
        params = {'sampling_params': sampling_params}
        # Use VLLM
        out = model.generate(prompts, **params)
        out = [o.outputs[0].text for o in out]
        print(out[0])
        results += out
        if count % 5 == 0:
            with open(f'temp_{args.n_run}', 'wb') as fout:
                pickle.dump({
                    'results_full': results,
                }, fout)
        count += 1
    return results, results_logprobs, results_perplexities, results_entropies, dataset["filename"]

#%%
def load_model_tokenizer():
    from vllm import LLM
    model = LLM(
        model_path,
        max_model_len=max_seq_length,
        gpu_memory_utilization=0.88,
        tensor_parallel_size=n_cuda,
        enforce_eager=True,
    )
    tokenizer = model.get_tokenizer()
    return model, tokenizer

#%%
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2_prompt", action="store_true")
    parser.add_argument("--model_name", default="qwen3", choices=list(MODELS.keys()))
    parser.add_argument("--test_folder", type=str, default="sample_proof")
    parser.add_argument("--n_run", type=int)
    args = parser.parse_args()
    model_path, n_cuda = MODELS[args.model_name]

    max_seq_length = 11264*3  # Can increase for longer reasoning traces
    lora_rank = 32  # Larger rank = smarter, but slower
    max_prompt_length = 9728

    prefix = args.test_folder
    source_dir = f"data/{prefix}/"
    files = [f for f in sorted(os.listdir(source_dir)) if f.endswith('.txt')]

    base_module, overrides_module = get_prompt_modules(args.v2_prompt)
    score_template = get_var("score_template", base_module, overrides_module)
    output_template = get_var("output_template", base_module, overrides_module)

    score_template += output_template
    prompt_builder = init_prompt_builder(score_template)

    dataset_save_path = "save/dataset_" + prefix
    if os.path.exists(dataset_save_path):
        dataset = DatasetDict.load_from_disk(dataset_save_path)
    else:
        full_data = load_sle_data(files)
        dataset = DatasetDict({
            "full": Dataset.from_list(full_data),
        })
        print('Saving dataset to disk...')
        dataset.save_to_disk(dataset_save_path)

    results_dir = 'results_inference' + f'/{prefix}_{args.model_name}_{args.n_run}/'
    os.makedirs(results_dir, exist_ok=True)
    pkl_path = results_dir+f'outputs{"_V2" if args.v2_prompt else ""}.pkl'
    to_run_inference = True
    results_train, results_test = [], []
    data = None
    if os.path.exists(pkl_path):
        with open(pkl_path, 'rb') as f:
            data = pickle.load(f)
    if data and 'results_full' in data:
        print(f'Inference already done and saved at {pkl_path}!')
        to_run_inference = False
    if to_run_inference:
        print("Beginning inference...")
        model, tokenizer = load_model_tokenizer()
        import time
        t1 = time.time()
        results_full, results_logprobs_full, results_perplexities_full, results_entropies_full, filenames_full = inference(dataset["full"])
        t2 = time.time()
        with open(pkl_path, 'wb') as f:
            pickle.dump({
                'full_runtime': t2-t1,
                'results_full': results_full,
                'filenames_full': filenames_full,
            }, f)
