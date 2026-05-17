# second layer of LLM framework
# verifies whether model output has errors

import argparse
from datasets import DatasetDict, Dataset
import numpy as np
import json
import pickle
import time
import os
from torch.utils.data import DataLoader
from tqdm import tqdm
from vllm import LLM
from prompts.prompt import (
    keywords_list,
    type_a_hard,
    type_b,
    npsle_tips,
)
from recipes import MODELS
from grpo import (
    compute_avglogprob_and_entropy,
    SYSTEM_PROMPT,
    get_prompt_modules,
    get_var,
)
from utils.grpo_utils import init_prompt_builder, extract_xml_answer, load_sampling_params, parse_output


def build_template(base, overrides, v2_prompt):
    guidelines_template = get_var("guidelines_template", base, overrides)
    output_template = get_var("output_template", base, overrides)
    clinical_note_details = '' if v2_prompt else ' dated {{ date }} (dd/mm/yyyy)'

    template = '''
You are a verifier tasked with ensuring that a model-generated output complies with a set of predefined rules.

Below are the rules:''' + guidelines_template + output_template + '''

Common errors to watch for (not limited to):
- Time classification: terms like "onset" indicate symptoms are still active.
- Diagnostic keyword interpretation: the presence of diagnostic keywords may be sufficient to mark criteria_fulfilled, even if not all formal criteria elements are explicitly listed in the note.
- Time and criteria validation: To support `score = 1`, time must fall within either within_10days or 11_to_30days, and the corresponding criteria must be fulfilled.
- Incomplete keyword scanning: ensure all relevant keyword mentions are identified across the entire clinical note, not just in one area.

=========================================
Here is the clinical note''' + clinical_note_details +''':
{{ clinical_note }}

=========================================
Here is the model output to evaluate:
{{ model_output }}

=========================================
Your task:
1. Review the output against each rule.
2. Identify any errors or omissions.
3. Correct the output to fully comply with the rules.
4. Return the final corrected output only.

Important:
- The final output must follow the same format as the original.
- If the original output is already correct, return it unchanged.

'''
    return template

# required parameters:
# descriptor, treatment_logic, information, keywords, nature_of_intention_to_treat
# date, clinical_note, model_output


def load_model_and_tokenizer(model_name, n_cuda):
    model = LLM(
        model_name,
        max_model_len=max_seq_length,
        gpu_memory_utilization=0.9,
        tensor_parallel_size=n_cuda,
        enforce_eager=True,
    )
    tokenizer = model.get_tokenizer()
    return model, tokenizer


def build_prompt(source_dir, file, descrip, model_output, template, base, overrides, prompt_builder):
    nature_of_intention_to_treat_prompt = get_var("nature_of_intention_to_treat_prompt", base, overrides)
    intention_to_treat_prompt = get_var("intention_to_treat_prompt", base, overrides)
    treatment_response_prompt = get_var("treatment_response_prompt", base, overrides)
    definitions = dict(base.definitions)
    if overrides and hasattr(overrides, "definitions"):
        definitions.update(overrides.definitions)

    with open(source_dir + file) as f:
        clinical_note = f.read()

    date = file.split("-")[-1].split(".")[0]
    date = f"{date[6:]}/{date[4:6]}/{date[:4]}"
    keywords = ""
    if "diagnostic" in keywords_list[descrip]:
        keywords += (
            "\nList of diagnostic keywords:\n"
            + keywords_list[descrip]["diagnostic"]
        )
    elif descrip not in type_b:
        keywords += "\nNo diagnostic keywords."
    if "symptoms" in keywords_list[descrip]:
        keywords += (
            "\nList of symptoms/signs keywords:\n"
            + keywords_list[descrip]["symptoms"]
        )
    if "paraclinical" in keywords_list[descrip]:
        keywords += (
            "\nList of paraclinical keywords:\n"
            + keywords_list[descrip]["paraclinical"]
        )
    if "keywords" in keywords_list[descrip]:
        keywords += (
            "\nList of keywords:\n"
            + keywords_list[descrip]["keywords"]
        )
    treatment_logic = (
        intention_to_treat_prompt
        if descrip in type_a_hard
        else treatment_response_prompt
    )
    nature_of_intention_to_treat = (
        nature_of_intention_to_treat_prompt
        if descrip in type_a_hard
        else ''
    )
    npsle_prompt = npsle_tips if descrip in type_a_hard else ""
    pargs = {
        "prompt_builder": {
            "descriptor": descrip,
            **({"date": date,} if "{{ date }}" in template else {}),
            "keywords": keywords,
            "npsle_tips": npsle_prompt,
            "information": definitions[descrip],
            "clinical_note": clinical_note,
            "treatment_logic": intentitreatment_logicon_to_treat,
            "nature_of_intention_to_treat": nature_of_intention_to_treat,
            "model_output": model_output,
        }
    }
    prompt = prompt_builder.run(pargs)["prompt_builder"]["prompt"]
    return prompt

def collate_fn(batch):
    batch_prompt = [item["prompt"] for item in batch]
    batch_answer = [item["answer"] for item in batch]
    return {"prompt": batch_prompt, "answer": batch_answer}

def build_dataset(source_dir, answers, outputs, filenames, grouped, template, base, overrides, prompt_builder):
    data = []
    # extract each output to build new prompt
    for a, o, f in zip(answers, outputs, filenames):
        try:
            parsed = parse_output(extract_xml_answer(o), is_lst=grouped)
        except:
            parsed = [] if grouped else {'score': '0' , 'confidence_score': '0', 'descriptor': a['descriptor']}
        new_prompt = build_prompt(source_dir, f, a['descriptor'], parsed, template, base, overrides, prompt_builder)
        datapoint = {
            'filename': f,
            'prompt': [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": new_prompt},
            ],
            'answer': a,
        }
        data.append(datapoint)
    dataset = Dataset.from_list(data)
    return dataset

def inference(dataset):
    sampling_params = load_sampling_params(args.verifier_model, use_deterministic=args.use_deterministic)
    batch_size = 64
    dataloader = DataLoader(
        dataset, batch_size=batch_size, shuffle=False, collate_fn=collate_fn
    )
    results, results_logprobs, results_perplexities, results_entropies = [], [], [], []
    for batch in tqdm(dataloader):
        prompts = tokenizer.apply_chat_template(
            batch["prompt"], tokenize=False, add_generation_prompt=True
        )
        out = model.generate(prompts, sampling_params=sampling_params)
        out = [o.outputs[0].text for o in out]
        print(out[0])
        results += out
    return results, results_logprobs, results_perplexities, results_entropies



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--use_deterministic", action="store_true")
    parser.add_argument("--v2_prompt", action="store_true") # redundant
    parser.add_argument("--model_to_check", default="qwen3", choices=list(MODELS.keys()))
    parser.add_argument("--test_full", action="store_true") # redundant
    parser.add_argument("--test_folder", type=str, default="sample458") # sample458, pseudo169
    parser.add_argument("--ratio", type=float, default=None)
    parser.add_argument("--n_run", type=int, required=True)
    parser.add_argument("--verifier_model", type=str, default="gptoss_120b", choices=['qwen3', 'gptoss_120b', 'gptoss'])
    args = parser.parse_args()


    max_seq_length = int(11264*3.5)
    prefix = args.test_folder
    source_dir = f"data/{prefix}/"
    grouped = False
    sample = 'full'
    model_name, n_cuda = {
        'gptoss': ('openai/gpt-oss-20b', 1),
        'qwen3': ('Qwen/Qwen3-32B', 2),
        'gptoss_120b': ('openai/gpt-oss-120b', 2),
    }[args.verifier_model]

    if grouped:
        prefix = 'grouped_' + prefix
    if args.ratio:
        prefix += f"_ratio{args.ratio}"

    results_dir = f'{prefix}_{args.model_to_check}_base{"_deterministic" if args.use_deterministic else ""}_{args.n_run}'
    path_name = f'outputs{"_V2" if args.v2_prompt else ""}'
    if os.path.exists(f'results_grpo/{results_dir}/{path_name}.json'):
        with open(f'results_grpo/{results_dir}/{path_name}.json') as f:
            results = json.load(f)
    else:
        with open(f'results_grpo/{results_dir}/{path_name}.pkl', 'rb') as f:
            results = pickle.load(f)
    outputs = results[f'results_{sample}']

    if args.v2_prompt:
        prefix += '_V2'

    dataset_save_path = f'save/dataset_{prefix}/'
    dataset = DatasetDict.load_from_disk(dataset_save_path)
    filenames = dataset[sample]['filename']
    answers = dataset[sample]['answer']
    base, overrides = get_prompt_modules(args.v2_prompt)
    template = build_template(base, overrides, args.v2_prompt)
    prompt_builder = init_prompt_builder(template)

    dataset = build_dataset(source_dir, answers, outputs, filenames, grouped, template, base, overrides, prompt_builder)
    model, tokenizer = load_model_and_tokenizer(model_name, n_cuda)
    t1 = time.time()
    new_outputs, new_logprobs, new_perplexities, new_entropies = inference(dataset)
    t2 = time.time()

    with open(f'results_grpo/{results_dir}/{path_name}_verified_{args.verifier_model}.pkl', 'wb') as f:
        pickle.dump({
            f'{sample}_runtime': t2-t1,
            f'results_{sample}': new_outputs,
            f'answers_{sample}': answers,
            f'filenames_{sample}': filenames,
        }, f)
