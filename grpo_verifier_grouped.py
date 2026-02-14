# second layer of LLM framework (grouped descriptors prompt)
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
from prompts.prompt_grouped import (
    guidelines_template1,
    guidelines_template2_typea,
    guidelines_template2_typeb,
    guidelines_template3,
    output_template,
)
from prompts.prompt import (
    definitions,
    keywords_list,
    type_a_hard,
    type_b,
    npsle_tips,
)
from recipes import MODELS
from grpo import extract_xml_answer, compute_avglogprob_and_entropy, SYSTEM_PROMPT
from utils.grpo_utils import init_prompt_builder, load_sampling_params, parse_output


def get_template(guidelines_template):
    return '''
You are a verifier tasked with ensuring that a model-generated output complies with a set of predefined rules.

Below are the rules:''' + guidelines_template + output_template + '''

Common errors to watch for (not limited to):
- Time classification: terms like "onset" indicate symptoms are still active.
- Diagnostic keyword interpretation: the presence of diagnostic keywords may be sufficient to mark criteria_fulfilled, even if not all formal criteria elements are explicitly listed in the note.
- Time and criteria validation: To support `score = 1`, time must fall within either within_10days or 11_to_30days, and the corresponding criteria must be fulfilled.
- Incomplete keyword scanning: ensure all relevant keyword mentions are identified across the entire clinical note, not just in one area.

=========================================
Here is the clinical note dated {{ date }} (dd/mm/yyyy):
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


def build_prompt(source_dir, file, descriptors, prompt_builder, npsle_prompt, model_output):
    with open(source_dir + file) as f:
        clinical_note = f.read()

    date = file.split("-")[-1].split(".")[0]
    date = f"{date[6:]}/{date[4:6]}/{date[:4]}"
    descriptor_list = []
    information = ""
    for descrip in descriptors:
        descriptor_list.append(descrip)
        descrip_point = '8-point' if descrip in type_a_hard else 'non 8-point'
        information += f"\n==== Information for {descrip} ({descrip_point}) ====\n"
        information += definitions[descrip]
        keywords = ""
        if "diagnostic" in keywords_list[descrip]:
            keywords += (
                "\nList of diagnostic keywords:\n"
                + keywords_list[descrip]["diagnostic"]
            )
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
        keywords += "\n"
        information += keywords
    pargs = {
        "prompt_builder": {
            "descriptor_list": descriptor_list,
            "date": date,
            "npsle_tips": npsle_prompt,
            "information": information,
            "clinical_note": clinical_note,
            "model_output": model_output,
        }
    }
    prompt = prompt_builder.run(pargs)["prompt_builder"]["prompt"]
    return prompt

def collate_fn(batch):
    batch_prompt = [item["prompt"] for item in batch]
    batch_answer = [item["answer"] for item in batch]
    return {"prompt": batch_prompt, "answer": batch_answer}

def build_dataset():
    data = []
    # extract each output to build new prompt
    for ans, o, f in zip(answers, outputs, filenames):
        try:
            parsed = parse_output(extract_xml_answer(o), is_lst=True)
        except:
            parsed = []
        descrips = [a['descriptor'] for a in ans]
        prompt_builder = prompt_builder_typeb if descrips[0] in type_b else prompt_builder_typea
        npsle_prompt = "" if descrips[0] in type_b else npsle_tips
        new_prompt = build_prompt(source_dir, f, descrips, prompt_builder, npsle_prompt, parsed)
        datapoint = {
            'filename': f,
            'prompt': [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": new_prompt},
            ],
            'answer': ans,
        }
        data.append(datapoint)
    dataset = Dataset.from_list(data)
    # dataset.save_to_disk(dataset_save_path[:-1]+f'_layer2_{sample}/')
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
    parser.add_argument("--model_to_check", default="qwen3", choices=list(MODELS.keys()))
    parser.add_argument("--test_folder", type=str, default="sample658")
    parser.add_argument("--n_run", type=int, required=True)
    parser.add_argument("--test_full", action="store_true")
    parser.add_argument("--use_deterministic", action="store_true")
    parser.add_argument("--verifier_model", type=str, default="gptoss_120b", choices=['qwen3', 'gptoss_120b', 'gptoss'])
    args = parser.parse_args()


    max_seq_length = int(11264*3.5)
    prefix = args.test_folder
    source_dir = f"data/{prefix}/"
    sample = 'test'
    if args.test_full:
        sample = 'full'
    model_name, n_cuda = {
        'gptoss': ('openai/gpt-oss-20b', 1),
        'qwen3': ('Qwen/Qwen3-32B', 4),
        'gptoss_120b': ('openai/gpt-oss-120b', 4),
    }[args.verifier_model]


    prefix = 'grouped_' + prefix

    dataset_save_path = f'save/dataset_{prefix}_ratio1.0/'
    dataset = DatasetDict.load_from_disk(dataset_save_path)
    filenames = dataset[sample]['filename']
    answers = dataset[sample]['answer']

    results_dir = f'{prefix}_ratio1.0_{args.model_to_check}_base{"_deterministic" if args.use_deterministic else ""}_{args.n_run}'
    if os.path.exists(f'results_grpo/{results_dir}/outputs.json'):
        with open(f'results_grpo/{results_dir}/outputs.json') as f:
            results = json.load(f)
    else:
        with open(f'results_grpo/{results_dir}/outputs.pkl', 'rb') as f:
            results = pickle.load(f)
    outputs = results[f'results_{sample}']

    template_typea = get_template(guidelines_template1 + guidelines_template2_typea + guidelines_template3)
    template_typeb = get_template(guidelines_template1 + guidelines_template2_typeb + guidelines_template3)
    prompt_builder_typea = init_prompt_builder(template_typea)
    prompt_builder_typeb = init_prompt_builder(template_typeb)

    dataset = build_dataset()
    
    model, tokenizer = load_model_and_tokenizer(model_name, n_cuda)
    t1 = time.time()
    new_outputs, new_logprobs, new_perplexities, new_entropies = inference(dataset)
    t2 = time.time()

    with open(f'results_grpo/{results_dir}/outputs_verified_{args.verifier_model}.pkl', 'wb') as fout:
        pickle.dump({
            f'{sample}_runtime': t2-t1,
            f'results_{sample}': new_outputs,
            f'filenames_{sample}': filenames,
        }, fout)
