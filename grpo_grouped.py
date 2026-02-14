#%%
import argparse
from datasets import Dataset, DatasetDict
import json
import numpy as np
import os
import pandas as pd
import pickle
import re
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, confusion_matrix
from torch.utils.data import DataLoader
from tqdm import tqdm
from prompts.prompt import (
    descriptors,
    keywords_list,
    type_a_hard,
    type_a_others,
    type_b,
    npsle_tips,
)
from grpo import summarise_annotations_reasoning, compute_avglogprob_and_entropy, get_prompt_modules, DIAGNOSTIC_DEFAULT
from prompts.prompt_grouped import (
    guidelines_template1,
    guidelines_template2_typea,
    guidelines_template2_typeb,
    guidelines_template3,
    note_template,
    output_template
)
from utils.grpo_utils import (
    init_prompt_builder,
    extract_xml_answer,
    get_template_from_prompt_builder,
    load_sampling_params,
    parse_output,
    SYSTEM_PROMPT,
)
from recipes import MODELS
import importlib


def get_split_filenames(dataset_save_path):
    dataset = DatasetDict.load_from_disk(dataset_save_path)
    descriptors = set(a['descriptor'] for a in dataset['train']['answer'])
    return dataset['train']['filename'], dataset['test']['filename'], dataset['full']['filename'], descriptors

def build_prompt(source_dir, file, descriptors, prompt_builder, npsle_prompt):
    # get definitions
    base, overrides = get_prompt_modules(False)
    definitions = dict(base.definitions)
    if overrides and hasattr(overrides, "definitions"):
        definitions.update(overrides.definitions)

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
                f"\nList of diagnostic keywords for {descrip}:\n"
                + keywords_list[descrip]["diagnostic"]
            )
        elif descrip not in type_b:
            keywords += "\nNo diagnostic keywords."
        if "symptoms" in keywords_list[descrip]:
            keywords += (
                f"\nList of symptoms/signs keywords for {descrip}:\n"
                + keywords_list[descrip]["symptoms"]
            )
        if "paraclinical" in keywords_list[descrip]:
            keywords += (
                f"\nList of paraclinical keywords for {descrip}:\n"
                + keywords_list[descrip]["paraclinical"]
            )
        if "keywords" in keywords_list[descrip]:
            keywords += (
                f"\nList of keywords for {descrip}:\n"
                + keywords_list[descrip]["keywords"]
            )
        keywords += "\n"
        information += keywords
    pargs = {
        "prompt_builder": {
            "descriptor_list": descriptor_list,
            **({"date": date,} if "{{ date }}" in get_template_from_prompt_builder(prompt_builder) else {}),
            "npsle_tips": npsle_prompt,
            "information": information,
            "clinical_note": clinical_note,
        }
    }
    prompt = prompt_builder.run(pargs)["prompt_builder"]["prompt"]
    return prompt

def load_sle_data(filenames, filtered_descriptors):
    data = []
    for _, row in df_ben.iterrows():
        file = row["filename"]
        if file not in filenames:
            continue
        filtered_descriptors_type_a = [d for d in filtered_descriptors if d in type_a_hard+type_a_others]
        filtered_descriptors_type_b = [d for d in filtered_descriptors if d in type_b]
        for descrips, prompt_builder, npsle_prompt, in zip(
            [filtered_descriptors_type_a, filtered_descriptors_type_b],
            [prompt_builder_typea, prompt_builder_typeb],
            [npsle_tips, ""],
        ):
            prompt = build_prompt(source_dir, file, descrips, prompt_builder, npsle_prompt)
            # truncate prompt
            if len(prompt) > max_seq_length:
                print('truncating prompt')
            prompt = prompt[:max_seq_length]
            answer = []
            for descrip in descrips:
                diagnostic = DIAGNOSTIC_DEFAULT
                criteria, time_label, intention, exclusions, treatment, = '', '', '', '', ''
                if descrip in row and not pd.isna(row[descrip]):
                    diagnostic, criteria, time_label, intention, exclusions, treatment = summarise_annotations_reasoning(eval(row[descrip]))
                score = df_scores[df_scores.filename == file][descrip].iloc[0]
                answer.append({
                    'descriptor': descrip,
                    'score': str(score),
                    'diagnostic': diagnostic,
                    'criteria': criteria,
                    'time_label': time_label,
                    'intention': intention,
                    'exclusions': exclusions,
                    'treatment': treatment,                    
                })
            datapoint = {
                "filename": file,
                "prompt": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "answer": answer,
            }
            data.append(datapoint)
    return data

#%%
def get_attribute_label_by_descrip(answers, attr_label):
    return [{a['descriptor']: a[attr_label] if a['diagnostic'] != DIAGNOSTIC_DEFAULT and attr_label in a else None for a in ans} for ans in answers]

def extract_by_descrip(answers, results):
    extracted_responses = [extract_xml_answer(r) for r in results]
    labels = {
        'score': [{a['descriptor']: 1 if a['score'] == '1' else 0 for a in ans} for ans in answers],
        'relevancy': [{a['descriptor']: 'true' if a['diagnostic'] != DIAGNOSTIC_DEFAULT else 'false' for a in ans} for ans in answers],
        'criteria': get_attribute_label_by_descrip(answers, 'criteria'),
        'time': get_attribute_label_by_descrip(answers, 'time_label'),
        'intention': get_attribute_label_by_descrip(answers, 'intention'),
        'diagnostic': get_attribute_label_by_descrip(answers, 'diagnostic'),
        'exclusions': get_attribute_label_by_descrip(answers, 'exclusions'),
        'treatment': get_attribute_label_by_descrip(answers, 'treatment'),
   }
    def default_values():
        return {k: v for k, v in {
            'score': 0, 'relevancy': 'false', 'criteria': None, 'time': None, 'intention': None,
        }.items()}
    extracted = {
        k: [{d: default_values()[k] for d in label.keys()} for label in labels['score']]
        for k in ['score', 'relevancy', 'criteria', 'time', 'intention']
    }
    extracted['length'] = [len(r) for r in extracted_responses]
    for i, r in enumerate(extracted_responses):
        try:
            parsed = parse_output(r, is_lst=True)
        except:
            continue
        if isinstance(parsed, list):
            for d in parsed:
                if not isinstance(d, dict) or 'descriptor' not in d:
                    continue
                descrip = d['descriptor']
                if 'score' in d and str(d['score']).strip() in ['0', '1']:
                    extracted['score'][i][descrip] = 1 if str(d['score']).strip() == '1' else 0
                if 'relevant' in d and str(d['relevant']).strip().lower() in ['true', 'false']:
                    extracted['relevancy'][i][descrip] = str(d['relevant']).strip().lower()
                if d.get('criteria'): extracted['criteria'][i][descrip] = d['criteria'].strip().lower()
                if d.get('time'): extracted['time'][i][descrip] = d['time'].strip().lower()
                if d.get('nature_of_intention_to_treat'):
                    extracted['intention'][i][descrip] = d['nature_of_intention_to_treat'].strip().lower()
    return labels, extracted

def evaluate(name, descrip, answers, results, file=None):
    labels, extracted = extract_by_descrip(answers, results)
    keys = ['score', 'relevancy', 'criteria', 'time', 'intention']
    labels_descrip = {k: [] for k in keys}
    extracted_descrip = {k: [] for k in keys}

    # Filter relevant descriptors based on target descriptor type
    for i, score_dict in enumerate(labels['score']):
        for label_descrip in score_dict.keys():
            if (
                label_descrip == descrip or
                descrip == 'total' or
                (descrip == 'type_a>=8' and label_descrip in type_a_hard) or
                (descrip == 'type_a<8' and label_descrip in type_a_others) or
                (descrip == 'type_b' and label_descrip in type_b)
            ):
                for k in keys:
                    labels_descrip[k].append(labels[k][i][label_descrip])
                    extracted_descrip[k].append(extracted[k][i][label_descrip])
    descrip_acc = accuracy_score(labels_descrip['score'], extracted_descrip['score'])
    descrip_pre = precision_score(labels_descrip['score'], extracted_descrip['score'], zero_division=np.nan)
    descrip_rec = recall_score(labels_descrip['score'], extracted_descrip['score'], zero_division=np.nan)
    descrip_f1 = f1_score(labels_descrip['score'], extracted_descrip['score'], zero_division=np.nan)
    tn, fp, fn, tp = confusion_matrix(labels_descrip['score'], extracted_descrip['score'], labels=[0,1]).ravel().tolist()
    print(f'{name} {descrip}\tscore acc: {descrip_acc}\tprecision: {descrip_pre}\trecall: {descrip_rec}\tF1: {descrip_f1}', file=file)
    print(f"{name} {descrip}\tTotal samples: {len(labels_descrip['score'])}\tTN: {tn}\tFP: {fp}\tFN: {fn}\tTP: {tp}", file=file)
    print(f'{name} {descrip}\tAvg length: ', np.mean(extracted['length']), file=file)
    return descrip_pre, descrip_rec, descrip_f1

def evaluate_by_descriptors(name, answers, results, file):
    all_descriptors = set([a['descriptor'] for ans in answers for a in ans])
    descrip_pres, descrip_recs, descrip_f1s = [], [], []
    for descrip in all_descriptors.union({'total', 'type_a>=8', 'type_a<8', 'type_b'}):
        pre, rec, f1 = evaluate(name, descrip, answers, results, file=file)
        if descrip in all_descriptors:
            descrip_pres.append(pre)
            descrip_recs.append(rec)
            descrip_f1s.append(f1)
    macro_pre = np.nanmean(descrip_pres)
    macro_rec = np.nanmean(descrip_recs)
    macro_f1 = np.nanmean(descrip_f1s)
    print(f'total_macro\tprecision: {macro_pre}\trecall: {macro_rec}\tF1: {macro_f1}', file=file)

def collate_fn(batch):
    batch_prompt = [item["prompt"] for item in batch]
    batch_answer = [item["answer"] for item in batch]
    return {"prompt": batch_prompt, "answer": batch_answer}

def inference(dataset):
    sampling_params = load_sampling_params(args.grpo_base_model, args.use_deterministic, args.disable_thinking)
    batch_size = 16
    dataloader = DataLoader(
        dataset, batch_size=batch_size, shuffle=False, collate_fn=collate_fn
    )
    results, results_logprobs, results_perplexities, results_entropies = [], [], [], []
    for batch in tqdm(dataloader):
        prompts = tokenizer.apply_chat_template(
            batch["prompt"], tokenize=False, add_generation_prompt=True
        )
        out = model.generate(prompts, sampling_params=sampling_params)
        token_ids_lst = [o.outputs[0].token_ids for o in out]
        token_logprobs_lst = [o.outputs[0].logprobs for o in out]
        out = [o.outputs[0].text for o in out]
        token_strs_lst = [tokenizer.convert_ids_to_tokens(token_ids) for token_ids in token_ids_lst]
        print(out[0])
        avg_logprobs, avg_entropies = zip(*[
            compute_avglogprob_and_entropy(token_strs, token_logprobs)
            for token_strs, token_logprobs in zip(token_strs_lst, token_logprobs_lst)
        ])
        perplexities = [np.exp(-avg_logprob) for avg_logprob in avg_logprobs]
        results += out
        results_logprobs += avg_logprobs
        results_perplexities += perplexities
        results_entropies += avg_entropies
    return results, results_logprobs, results_perplexities, results_entropies, dataset["answer"], dataset["filename"]

#%%
def load_model_tokenizer(model_path):
    from vllm import LLM
    model = LLM(
        base_model_path,
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
    parser.add_argument("--use_deterministic", action="store_true")
    parser.add_argument("--grpo_base_model", default="llama", choices=list(MODELS.keys()))
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--test_full", action="store_true")
    parser.add_argument("--test_folder", type=str, default="sample658") # sample458, pseudo169, sample658
    parser.add_argument("--sample_filter", type=str) # sample to include (e.g. sample242)
    parser.add_argument("--ckpt", type=int, default=100)
    parser.add_argument("--base", action="store_true")
    parser.add_argument("--ratio", type=float, default=1.0) # throw away unannotated & annotated NEGATIVE samples to reach certain ratio with POSITIVE samples
    parser.add_argument("--n_run", type=int)
    parser.add_argument("--disable_thinking", action="store_true")
    args = parser.parse_args()
    n_cuda = MODELS[args.grpo_base_model][1]
    base_model_path = MODELS[args.grpo_base_model][0]

    max_seq_length = int(11264*3.5)  # Can increase for longer reasoning traces
    lora_rank = 32  # Larger rank = smarter, but slower
    max_prompt_length = 9728

    prefix = args.test_folder
    source_dir = f"data/{prefix}/"
    benchmark_csv = f"data/{prefix}_entities_gold.csv"
    scores_csv = f"data/{prefix}_scores_gold.csv"
    df_ben = pd.read_csv(benchmark_csv)
    df_ben = df_ben[df_ben.filename.isin(os.listdir(source_dir))]
    df_scores = pd.read_csv(scores_csv)

    score_template_typea = guidelines_template1 + guidelines_template2_typea + guidelines_template3 + note_template
    score_template_typeb = guidelines_template1 + guidelines_template2_typeb + guidelines_template3 + note_template
    score_template_typea += output_template
    score_template_typeb += output_template
    prompt_builder_typea = init_prompt_builder(score_template_typea)
    prompt_builder_typeb = init_prompt_builder(score_template_typeb)

    prefix = 'grouped_' + prefix
    if args.ratio:
        prefix += f"_ratio{args.ratio}"
    dataset_save_path = "save/dataset_" + prefix
    suffix = prefix
    suffix += ("_" + args.grpo_base_model)
    checkpoint_dir = f"save/outputs_" + suffix
    model_save_path = checkpoint_dir + f"/checkpoint-{args.ckpt}" if not args.base else ''

    if os.path.exists(dataset_save_path):
        dataset = DatasetDict.load_from_disk(dataset_save_path)
    else:
        # build from non-grouped dataset
        train_filenames, test_filenames, full_filenames, filtered_descriptors = get_split_filenames(dataset_save_path.replace('grouped_', ''))
        train_data = load_sle_data(train_filenames, filtered_descriptors)
        test_data = load_sle_data(test_filenames, filtered_descriptors)
        full_data = load_sle_data(full_filenames, descriptors)
        dataset = DatasetDict({
            "train": Dataset.from_list(train_data),
            "test": Dataset.from_list(test_data),
            "full": Dataset.from_list(full_data),
        })
        dataset.save_to_disk(dataset_save_path)

    if not args.test:
        print('Grouped descriptor finetuning not supported.')
    else:
        print("Beginning inference...")
        results_dir = 'results_grpo'
        results_dir += f'/{suffix.replace("_V2", "")}' + ('_nothink' if args.disable_thinking else '') + ('_base' if args.base else str(args.ckpt)) + f'{"_deterministic" if args.use_deterministic else ""}_{args.n_run}/'
        os.makedirs(results_dir, exist_ok=True)
        path_name = 'outputs'
        pkl_path = results_dir+f'{path_name}.pkl'
        to_run_inference = True
        results_train, results_test = [], []
        if os.path.exists(pkl_path):
            with open(pkl_path, 'rb') as f:
                data = pickle.load(f)
                if 'results_full' in data:
                    results_full = data['results_full']
                    answers_full = dataset['full']['answer']
                    to_run_inference = False
                if not args.test_full:
                    for split in ['test', 'train']:
                        answers = dataset[split]['answer']
                        filenames = dataset[split]['filename']
                        locals()[f'answers_{split}'] = answers
                        locals()[f'filenames_{split}'] = filenames
                    if f'results_{split}' in data:
                        locals()[f'results_{split}'] = data[f'results_{split}']
        if to_run_inference:
            model, tokenizer = load_model_tokenizer(model_save_path if args.test and not args.base else base_model_path)
            import time
            t1 = time.time()
            if args.test_full:
                results_full, results_logprobs_full, results_perplexities_full, results_entropies_full, answers_full, filenames_full = inference(dataset["full"])
            else:
                results_test, results_logprobs_test, results_perplexities_test, results_entropies_test, answers_test, filenames_test = inference(dataset["test"])
                results_train, results_logprobs_train, results_perplexities_train, results_entropies_train, answers_train, filenames_train = inference(dataset["train"])
            t2 = time.time()
            with open(pkl_path, 'wb') as f:
                if args.test_full:
                    pickle.dump({
                        'full_runtime': t2-t1,
                        'results_full': results_full,
                        'results_logprobs_full': results_logprobs_full,
                        'results_perplexities_full': results_perplexities_full,
                        'results_entropies_full': results_entropies_full,
                        'filenames_full': filenames_full,
                    }, f)
                else:
                    pickle.dump({
                        'train_test_runtime': t2-t1,
                        'results_test': results_test,
                        'results_logprobs_test': results_logprobs_test,
                        'results_perplexities_test': results_perplexities_test,
                        'results_entropies_test': results_entropies_test,
                        'filenames_test': filenames_test,
                        'results_train': results_train,
                        'results_logprobs_train': results_logprobs_train,
                        'results_perplexities_train': results_perplexities_train,
                        'results_entropies_train': results_entropies_train,
                        'filenames_train': filenames_train,
                    }, f)
        if args.sample_filter: # make sure full is available
            with open(results_dir+f'performance_{args.sample_filter}.txt', 'w') as f:
                    sample = set([f for f in os.listdir(f'data/{args.sample_filter}') if f.endswith('.txt')])
                    sample_answers, sample_results = [], []
                    for ans, res, fil in zip(answers_full, results_full, filenames_full):
                        if fil in sample:
                            sample_answers.append(ans)
                            sample_results.append(res)
                    evaluate_by_descriptors('sample', sample_answers, sample_results, f)
        elif args.test_full:
            with open(results_dir+'performance.txt', 'w') as f:
                evaluate_by_descriptors('full', answers_full, results_full, f)
        else:
            if not results_train:
                for res, fil in zip(results_full, filenames_full):
                        if fil in filenames_train:
                            results_train.append(res)
            if not results_test:
                for res, fil in zip(results_full, filenames_full):
                        if fil in filenames_test:
                            results_test.append(res)
            with open(results_dir+'performance_train_test.txt', 'w') as f:
                evaluate_by_descriptors('test', answers_test, results_test, f)
                evaluate_by_descriptors('train', answers_train, results_train, f)
