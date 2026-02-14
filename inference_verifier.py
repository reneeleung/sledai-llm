# INFERENCE ONLY, NO GROUND TRUTHS
#%%
import argparse
from datasets import DatasetDict
import os
import pickle
from torch.utils.data import DataLoader
from tqdm import tqdm
from utils.grpo_utils import init_prompt_builder, load_sampling_params
from recipes import MODELS
from grpo import get_prompt_modules, get_var
from grpo_verifier import build_template, build_dataset

# Load and prep dataset
def collate_fn(batch):
    batch_prompt = [item["prompt"] for item in batch]
    return {"prompt": batch_prompt}

def inference(dataset):
    sampling_params = load_sampling_params(args.verifier_model)
    batch_size = 16
    dataloader = DataLoader(
        dataset, batch_size=batch_size, shuffle=False, collate_fn=collate_fn
    )
    results, results_logprobs, results_perplexities, results_entropies = [], [], [], []
    for batch in tqdm(dataloader):
        prompts = tokenizer.apply_chat_template(
            batch["prompt"], tokenize=False, add_generation_prompt=True
        )
        params = {'sampling_params': sampling_params}
        # Use VLLM
        out = model.generate(prompts, **params)
        out = [o.outputs[0].text for o in out]
        print(out[0])
        results += out
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
    parser.add_argument("--model_to_check", default="qwen3", choices=list(MODELS.keys()))
    parser.add_argument("--test_folder", type=str, default="sample_proof")
    parser.add_argument("--n_run", type=int)
    parser.add_argument("--verifier_model", default="gptoss_120b", choices=list(MODELS.keys()))
    args = parser.parse_args()
    model_path, n_cuda = MODELS[args.verifier_model]

    max_seq_length = 11264*3  # Can increase for longer reasoning traces
    lora_rank = 32  # Larger rank = smarter, but slower
    max_prompt_length = 9728

    prefix = args.test_folder
    source_dir = f"data/{prefix}/"
    files = [f for f in os.listdir(source_dir) if f.endswith('.txt')]

    results_dir = 'results_inference' + f'/{prefix}_{args.model_to_check}_{args.n_run}/'
    os.makedirs(results_dir, exist_ok=True)
    pkl_path = results_dir+f'outputs{"_V2" if args.v2_prompt else ""}.pkl'
    with open(pkl_path, 'rb') as f:
        results = pickle.load(f)
    outputs = results['results_full']

    base_module, overrides_module = get_prompt_modules(args.v2_prompt)
    score_template = get_var("score_template", base_module, overrides_module)
    output_template = get_var("output_template", base_module, overrides_module)

    score_template += output_template
    prompt_builder = init_prompt_builder(score_template)

    dataset_save_path = "save/dataset_" + prefix
    dataset = DatasetDict.load_from_disk(dataset_save_path)

    filenames = dataset['full']['filename']
    answers = dataset['full']['answer']
    base, overrides = get_prompt_modules(args.v2_prompt)
    template = build_template(base, overrides, args.v2_prompt)
    prompt_builder = init_prompt_builder(template)

    dataset = build_dataset(source_dir, answers, outputs, filenames, False, template, base, overrides, prompt_builder)

    pkl_path = pkl_path.replace('.pkl', f'_verified_{args.verifier_model}.pkl')
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
        results_full, results_logprobs_full, results_perplexities_full, results_entropies_full, filenames_full = inference(dataset)
        t2 = time.time()
        with open(pkl_path, 'wb') as f:
            pickle.dump({
                'full_runtime': t2-t1,
                'results_full': results_full,
                'filenames_full': filenames_full,
            }, f)
