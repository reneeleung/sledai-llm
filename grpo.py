#%%
import argparse
from datasets import Dataset, DatasetDict
import importlib
import json
import numpy as np
import os
import pandas as pd
import pickle
import re
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, confusion_matrix, mean_squared_error
from torch.utils.data import DataLoader
from tqdm import tqdm
from prompts.prompt import (
    descriptors,
    keywords_list,
    type_a_hard,
    type_a_others,
    type_b,
    npsle_tips,
    sledai_weights,
)
from utils.grpo_utils import (
    init_prompt_builder,
    extract_xml_answer,
    get_template_from_prompt_builder,
    parse_output,
    load_sampling_params,
    build_scores_df,
    get_final_scores,
    compute_weights_of_misclassified,
    SYSTEM_PROMPT,
)
from recipes import MODELS
from utils.grpo_rewards_utils import (
    normalize_text,
    split_entities,
    score_entities,
    extract_quoted_spans,
    nonlabel_quote_penalty,
    EXCLUSION_INTENT_WORDS,
    TREATMENT_INTENT_WORDS,
)
from utils.data_utils import (
    visualise_criteria,
    visualise_time,
    visualise_relevancy,
    visualise_exclusions,
    visualise_treatment,
)


DIAGNOSTIC_DEFAULT = "No mention of relevant symptoms or signs, tests, or diagnoses."
EXCLUSIONS_DEFAULT = "No exclusions found."
TREATMENT_DEFAULT = "No treatment found."

# Reward functions
def correctness_reward_func(completions, answer, **kwargs) -> list[float]:
    """Reward function that checks descriptor score correctness"""
    responses = [completion[0]["content"] for completion in completions]
    extracted_responses = [extract_xml_answer(r) for r in responses]
    extracted_answers = []
    for r in extracted_responses:
        try:
            r = parse_output(r)
            r = str(r['score'])
            extracted_answers.append(r)
        except:
            extracted_answers.append(r)
    label_scores = [ans["score"] for ans in answer]
    print(
        "-" * 20,
        f"\nAnswer:\n{label_scores[0]}",
        f"\nExtracted:\n{extracted_answers[0]}",
    )

    rewards = []
    for r, a in zip(extracted_answers, label_scores):
        if int(a) == 1 and not args.equal_correctness:
            # increase magniture of reward for correct positive samples
            rewards.append(4.0 if r == a else -4.0)
        else:
            rewards.append(2.0 if r == a else -2.0)
    return rewards

def json_reward_func(completions, **kwargs) -> list[float]:
    responses = [completion[0]["content"] for completion in completions]
    extracted_responses = [extract_xml_answer(r) for r in responses]
    rewards = []
    for r in extracted_responses:
        try:
            parsed = parse_output(r)
            rewards.append(0.5 if str(parsed.get('score', '')).isdigit() else 0)
        except:
            rewards.append(0)
    return rewards

# ======= Evaluate attributes =======
def extract_value(response, json_attr):
    response = extract_xml_answer(response)
    try:
        parsed = parse_output(response)
        json_value = parsed[json_attr]
        return str(json_value).lower()
    except:
        print('Cannot parse: ', json_attr, response)
        return 'false'

def evaluate_attribute(response, label, json_attr):
    return extract_value(response, json_attr) == label

def reasoning_reward_func_relevancy(completions, answer, **kwargs) -> list[float]:
    rewards = []
    labels_diagnostic = [ans["diagnostic"] for ans in answer]
    responses = [completion[0]["content"] for completion in completions]
    for label_diagnostic, response in zip(labels_diagnostic, responses):
        correct = evaluate_attribute(response, 'true' if label_diagnostic != DIAGNOSTIC_DEFAULT else 'false', 'relevant')
        rewards.append(1 if correct else -1)
    return rewards

def reasoning_reward_func_criteria(completions, answer, **kwargs) -> list[float]:
    rewards = []
    labels_diagnostic = [ans["diagnostic"] for ans in answer]
    responses = [completion[0]["content"] for completion in completions]
    for label_diagnostic, response in zip(labels_diagnostic, responses):
        if label_diagnostic == DIAGNOSTIC_DEFAULT:
            rewards.append(np.nan)
        else:
            correct = evaluate_attribute(response,  answer[0]["criteria"], 'criteria')
            rewards.append(1 if correct else -1)
    return rewards

def reasoning_reward_func_time(completions, answer, **kwargs) -> list[float]:
    rewards = []
    labels_diagnostic = [ans["diagnostic"] for ans in answer]
    responses = [completion[0]["content"] for completion in completions]
    for label_diagnostic, response in zip(labels_diagnostic, responses):
        if label_diagnostic == DIAGNOSTIC_DEFAULT:
            rewards.append(np.nan)
        else:
            correct = evaluate_attribute(response, answer[0]["time_label"], 'time')
            rewards.append(1 if correct else -1)
    return rewards

def reasoning_reward_func_intention(completions, answer, **kwargs) -> list[float]:
    rewards = []
    labels_diagnostic = [ans["diagnostic"] for ans in answer]
    responses = [completion[0]["content"] for completion in completions]
    for label_diagnostic, response, ans in zip(labels_diagnostic, responses, answer):
        if label_diagnostic == DIAGNOSTIC_DEFAULT or not ans["intention"]:
            rewards.append(np.nan)
        else:
            correct = evaluate_attribute(response, answer[0]["intention"], 'nature_of_intention_to_treat')
            rewards.append(1 if correct else -1)
    return rewards

# ===== Evaluate reasoning (keywords in clinical text) =======
def extract_reasoning_and_rationale(response):
    xml = extract_xml_answer(response)
    try:
        parsed = parse_output(xml)
        rationale = parsed.get('rationale', '') or ''
    except Exception:
        rationale = ''
    m = re.search(r'<reasoning>(.*?)</reasoning>', response, flags=re.DOTALL | re.IGNORECASE)
    reasoning_trace = m.group(1) if m else ''
    reasoning_trace_norm = normalize_text(reasoning_trace)
    rationale_norm = normalize_text(rationale)
    combined = f"{reasoning_trace_norm} {rationale_norm}".strip()
    return reasoning_trace_norm, rationale_norm, combined


def reasoning_reward_func_diagnostic(completions, answer, **kwargs):
    rewards = []
    labels_diagnostic = [ans["diagnostic"] for ans in answer]
    responses = [completion[0]["content"] for completion in completions]
    for label_diagnostic, response in zip(labels_diagnostic, responses):
        if label_diagnostic == DIAGNOSTIC_DEFAULT:
            rewards.append(np.nan)
            continue
        _, _, text = extract_reasoning_and_rationale(response)
        base = score_entities(label_diagnostic, text, is_gated=False, intent_words=[])
        diag_entities = split_entities(label_diagnostic)
        quoted_spans = extract_quoted_spans(text)
        penalty = nonlabel_quote_penalty(text, quoted_spans, diag_entities)
        rewards.append(max(0.0, min(1.0, base - penalty)))
    return rewards

def reasoning_reward_func_exclusions(completions, answer, **kwargs):
    rewards = []
    labels_diagnostic = [ans["diagnostic"] for ans in answer]
    responses = [completion[0]["content"] for completion in completions]
    for label_diagnostic, response, ans_item in zip(labels_diagnostic, responses, answer):
        if label_diagnostic == DIAGNOSTIC_DEFAULT:
            rewards.append(np.nan)
            continue
        _, _, text = extract_reasoning_and_rationale(response)
        label_exclusions = ans_item.get("exclusions", EXCLUSIONS_DEFAULT)
        if label_exclusions == EXCLUSIONS_DEFAULT or not label_exclusions.strip():
            rewards.append(np.nan)
            continue
        base = score_entities(label_exclusions, text, is_gated=True, intent_words=EXCLUSION_INTENT_WORDS)
        label_entities_all = split_entities(ans_item.get("diagnostic", "")) + split_entities(label_exclusions)
        quoted_spans = extract_quoted_spans(text)
        penalty = nonlabel_quote_penalty(text, quoted_spans, label_entities_all)
        rewards.append(max(0.0, min(1.0, base - penalty)) * 0.5)
    return rewards

def reasoning_reward_func_treatment(completions, answer, **kwargs):
    rewards = []
    labels_diagnostic = [ans["diagnostic"] for ans in answer]
    responses = [completion[0]["content"] for completion in completions]
    for label_diagnostic, response, ans_item in zip(labels_diagnostic, responses, answer):
        if label_diagnostic == DIAGNOSTIC_DEFAULT:
            rewards.append(np.nan)
            continue
        _, _, text = extract_reasoning_and_rationale(response)
        label_treatment = ans_item.get("treatment", TREATMENT_DEFAULT)
        if label_treatment == TREATMENT_DEFAULT or not label_treatment.strip():
            rewards.append(np.nan)
            continue
        base = score_entities(label_treatment, text, is_gated=True, intent_words=TREATMENT_INTENT_WORDS)
        label_entities_all = split_entities(ans_item.get("diagnostic", "")) + split_entities(label_treatment)
        quoted_spans = extract_quoted_spans(text)
        penalty = nonlabel_quote_penalty(text, quoted_spans, label_entities_all)
        rewards.append(max(0.0, min(1.0, base - penalty)) * 0.5)
    return rewards

def count_xml(text) -> float:
    count = 0.0
    if text.count("<reasoning>\n") == 1:
        count += 0.125
    if text.count("\n</reasoning>\n") == 1:
        count += 0.125
    if text.count("\n<answer>\n") == 1:
        count += 0.125
        count -= len(text.split("\n</answer>\n")[-1]) * 0.001
    if text.count("\n</answer>") == 1:
        count += 0.125
        count -= (len(text.split("\n</answer>")[-1]) - 1) * 0.001
    return count

def xmlcount_reward_func(completions, **kwargs) -> list[float]:
    contents = [completion[0]["content"] for completion in completions]
    return [count_xml(c) for c in contents]

#%%
def summarise_annotations_reasoning(anns):
    diagnostic, criteria, exclusions, intention_to_treat, treatment, time_labels = [], [], [], [], [], []
    for tagged in anns:
        diagnostic_reasoning = tagged['matched'].replace('\n', ' ')
        criterion = tagged['criteria'].split('criteria_')[-1]
        # intention to treat
        intention_reasoning = ''
        if 'nature_of_intention_to_treat' in tagged:
            intention_reasoning = tagged['nature_of_intention_to_treat']
        # exclusions
        exclusions_reasoning = ''
        if 'Exclusions' in tagged:
            exclusions_reasoning = '\n'.join(tagged['Exclusions'])
        # treatment
        treatment_reasoning = ''
        if 'Treatment_response' in tagged:
            treatment_reasoning += '\n'.join(tagged['Treatment_response'])
        if 'Intention_to_treat' in tagged:
            treatment_reasoning += '\n'.join(tagged['Intention_to_treat'])
        criteria.append(criterion)
        diagnostic.append(diagnostic_reasoning)
        intention_to_treat.append(intention_reasoning)
        exclusions.append(exclusions_reasoning)
        treatment.append(treatment_reasoning)
        time_labels.append(tagged['time'])
    diagnostic = '\n'.join(diagnostic)
    exclusions = '\n'.join(exclusions)
    treatment = '\n'.join(treatment)
    if not exclusions.strip():
        exclusions = EXCLUSIONS_DEFAULT
    if not treatment.strip():
        treatment = TREATMENT_DEFAULT
    def select_by_priority(labels, priority):
        for i in priority:
            if i in labels:
                return i
        return None
    criterion_chosen = select_by_priority(set(criteria), ['fulfilled', 'unfulfilled_diagnostic', 'unfulfilled_negated', 'uncertain'])
    count = criteria.count(criterion_chosen)
    if count == 1:
        idx = criteria.index(criterion_chosen)
        time_label = time_labels[idx]
    else:
        time_label = select_by_priority(set(time_labels), ['within_10days', '11_to_30days', '30days_ago', 'time_uncertain'])
    intention = select_by_priority(set(intention_to_treat), ['treat_escalated', 'wait_and_see', 'treat_de_escalate'])
    return diagnostic, criterion_chosen, time_label, intention, exclusions, treatment

#%%
def split_pids(df_scores, train_ratio=0.5, seed=51):
    import random
    random.seed(seed)
    files = df_scores.filename.tolist()
    train_pids, test_pids = set(), set()
    # 1. sort the descriptors in order of occurrence
    counts = df_scores.iloc[:, 1:-1].sum() # remove filename and final_score columns
    descriptors_inorder = counts[(counts >= 2) & (counts <= 15)].sort_values().index.tolist() # only select those with >=2 and <15 scored reports
    # 2. from the least scored descriptor, distibute balanced pids to train/test
    for descrip in descriptors_inorder:
        scored = df_scores[df_scores[descrip] == 1].filename.tolist()
        scored_pids = list(set([f.split('-')[0] for f in scored]) - train_pids - test_pids) # filter out already added pids
        random.shuffle(scored_pids)
        n_train_pids = int(len(scored_pids)*train_ratio)
        train_pids = train_pids.union(set(scored_pids[:n_train_pids]))
        test_pids = test_pids.union(set(scored_pids[n_train_pids:]))

    pids = set([f.split('-')[0] for f in files])
    # 3. split remaining pids
    remaining_pids = list(pids-train_pids-test_pids)
    random.shuffle(remaining_pids)

    desired_train_size = int(train_ratio * len(pids))
    current_train_size = len(train_pids)
    n_train_pids = desired_train_size - current_train_size
    n_train_pids = max(0, min(n_train_pids, len(remaining_pids)))

    train_pids = train_pids.union(set(remaining_pids[:n_train_pids]))
    test_pids = test_pids.union(set(remaining_pids[n_train_pids:]))
    filtered_descriptors = counts[counts >=2].index.tolist()
    return train_pids, test_pids, pids, filtered_descriptors

def build_prompt(source_dir, file, descrip, prompt_builder, v2_prompt):
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
    base, overrides = get_prompt_modules(v2_prompt)
    nature_of_intention_to_treat_prompt = get_var("nature_of_intention_to_treat_prompt", base, overrides)
    intention_to_treat_prompt = get_var("intention_to_treat_prompt", base, overrides)
    treatment_response_prompt = get_var("treatment_response_prompt", base, overrides)
    definitions = dict(base.definitions)
    if overrides and hasattr(overrides, "definitions"):
        definitions.update(overrides.definitions)
    intention_to_treat = (
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
            **({"date": date,} if "{{ date }}" in get_template_from_prompt_builder(prompt_builder) else {}),
            "keywords": keywords,
            "npsle_tips": npsle_prompt,
            "information": definitions[descrip],
            "clinical_note": clinical_note,
            "intention_to_treat": intention_to_treat,
            "nature_of_intention_to_treat": nature_of_intention_to_treat,
        }
    }
    prompt = prompt_builder.run(pargs)["prompt_builder"]["prompt"]
    return prompt

def load_sle_data(pids):
    data = []
    for _, row in df_ben.iterrows():
        file = row["filename"]
        if file.split('-')[0] not in pids:
            continue
        for descrip in descriptors:
            prompt = build_prompt(source_dir, file, descrip, prompt_builder, args.v2_prompt)
            # truncate prompt
            prompt = prompt[:max_seq_length]
            diagnostic = DIAGNOSTIC_DEFAULT
            criteria, time_label, intention, exclusions, treatment, = '', '', '', '', ''
            if descrip in row and not pd.isna(row[descrip]):
                diagnostic, criteria, time_label, intention, exclusions, treatment = summarise_annotations_reasoning(eval(row[descrip]))
            answer = df_scores[df_scores.filename == file][descrip].iloc[0]
            datapoint = {
                "filename": file,
                "prompt": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "answer": {
                    'descriptor': descrip,
                    'score': str(answer),
                    'diagnostic': diagnostic,
                    'criteria': criteria,
                    'time_label': time_label,
                    'intention': intention,
                    'exclusions': exclusions,
                    'treatment': treatment,
                },
            }
            data.append(datapoint)
    return data

#%%
def visualise_data(data, save_fig='annotation_distributions.png'):
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    diagnostic_default_count = sum(d['answer']['diagnostic'] == DIAGNOSTIC_DEFAULT for d in data)
    exclusions_default_count = sum(d['answer']['exclusions'] == EXCLUSIONS_DEFAULT for d in data if d['answer']['exclusions'])
    treatment_default_count = sum(d['answer']['treatment'] == TREATMENT_DEFAULT for d in data if d['answer']['treatment'])
    diagnostic_other_count = len(data) - diagnostic_default_count
    exclusions_other_count = diagnostic_other_count - exclusions_default_count
    treatment_other_count = diagnostic_other_count - treatment_default_count
    criterias = [d['answer']['criteria'] for d in data if d['answer']['diagnostic'] != DIAGNOSTIC_DEFAULT]
    times = [d['answer']['time_label'] for d in data if d['answer']['time_label']]

    descrip_labels = {}
    for descrip in descriptors:
        descrip_total = sum(d['answer']['descriptor'] == descrip for d in data)
        descrip_annotated = sum( d['answer']['descriptor'] == descrip and d['answer']['diagnostic'] != DIAGNOSTIC_DEFAULT and d['answer']['score'] == '0' for d in data)
        descrip_score1 = sum( d['answer']['descriptor'] == descrip and d['answer']['score'] == '1' for d in data)
        descrip_labels[descrip] = {
            'scored': descrip_score1,
            'annotated_unscored': descrip_annotated,
            'unannotated': descrip_total-descrip_annotated-descrip_score1,
        }

    fig = plt.figure(figsize=(15,10))
    gs = gridspec.GridSpec(2, 5, height_ratios=[1,1])
    counts = [diagnostic_default_count, diagnostic_other_count]
    ax0 = fig.add_subplot(gs[0,0])
    visualise_relevancy(ax0, counts)
    ax1 = fig.add_subplot(gs[0,1])
    visualise_criteria(ax1, criterias)
    ax2 = fig.add_subplot(gs[0,2])
    visualise_time(ax2, times)
    counts = [exclusions_default_count, exclusions_other_count]
    ax3 = fig.add_subplot(gs[0,3])
    visualise_exclusions(ax3, counts)
    counts = [treatment_default_count, treatment_other_count]
    ax4 = fig.add_subplot(gs[0,4])
    visualise_treatment(ax4, counts)
    ax5 = fig.add_subplot(gs[1,:])
    x = np.arange(len(descrip_labels))
    width = 0.25
    rects1 = ax5.bar(x-width, [descrip_labels[descrip]['scored'] for descrip in descriptors], width, label='Scored')
    rects2 = ax5.bar(x, [descrip_labels[descrip]['annotated_unscored'] for descrip in descriptors], width, label='Annotated but unscored')
    rects3 = ax5.bar(x+width, [descrip_labels[descrip]['unannotated'] for descrip in descriptors], width, label='Unannotated')
    ax5.set_title('Descriptor Scores Distribution')
    ax5.set_xticks(x)
    ax5.set_xticklabels(descrip_labels.keys(), rotation=90)
    ax5.legend()
    def add_labels(rects):
        for rect in rects:
            height = rect.get_height()
            if height > 0:
                ax5.text(rect.get_x() + rect.get_width()/2, height+0.1, f'{height}', ha='center', va='bottom')
    add_labels(rects1)
    add_labels(rects2)
    add_labels(rects3)
    plt.tight_layout()
    if save_fig:
        plt.savefig(save_fig)

#%%
def random_sample_max(pool, k):
    import random
    seed = 51
    random.seed(seed)
    if len(pool) < k:
        return pool # get all
    else:
        return random.sample(pool, k=k)

def build_dataset(data, ratio, descriptors, min_scored=1):
    import random
    seed = 51
    random.seed(seed)
    pool = {}
    for descrip in descriptors:
        unannotated_data = [d for d in data if d['answer']['descriptor'] == descrip and d['answer']['diagnostic'] == DIAGNOSTIC_DEFAULT]
        annotated_unscored_data = [d for d in data if d['answer']['descriptor'] == descrip and d['answer']['score'] != '1' and d['answer']['diagnostic'] != DIAGNOSTIC_DEFAULT]
        descrip_scored = [d for d in data if d['answer']['descriptor'] == descrip and d['answer']['score'] == '1']
        if len(descrip_scored) >= min_scored:
            pool[descrip] = {
                'unannotated': unannotated_data,
                'annotated_unscored': annotated_unscored_data,
                'scored': descrip_scored,
            }
    print(f'# of descriptors with >={min_scored} scored samples: ', len(pool.keys()))
    print(pool.keys())

    # 2. balance scored vs annotated vs unannotated samples
    if ratio:
        for descrip in pool.keys():
            # maximum 20 scored
            n_scored = min(len(pool[descrip]['scored']), 20)
            pool[descrip]['scored'] = random.sample(pool[descrip]['scored'], k=n_scored)
            pool[descrip]['unannotated'] = random.sample(pool[descrip]['unannotated'], k=int(n_scored*ratio))
            # keep samples with exclusions or treatment
            exclusions = [d for d in pool[descrip]['annotated_unscored'] if d['answer']['exclusions'] != EXCLUSIONS_DEFAULT]
            treatment = [d for d in pool[descrip]['annotated_unscored'] if d['answer']['treatment'] != TREATMENT_DEFAULT and d not in exclusions]
            to_keep = exclusions + treatment
            remaining = [d for d in pool[descrip]['annotated_unscored'] if d not in to_keep]
            # first fill from exclusions or treatment
            annotated_unscored = []
            annotated_unscored += random_sample_max(to_keep, k=int(n_scored*ratio))
            filled_len = len(annotated_unscored)
            # if not enough samples, then fill from remaining
            if filled_len < int(n_scored*ratio):
                annotated_unscored += random_sample_max(remaining, k=int(n_scored*ratio)-filled_len)
            pool[descrip]['annotated_unscored'] = annotated_unscored

    # 3. stratified split annotated samples into train and test for each descriptor (75% and 25%)
    filtered_data = []
    for descrip in pool.keys():
        filtered_data += pool[descrip]['scored']
        filtered_data += pool[descrip]['annotated_unscored']
        filtered_data += pool[descrip]['unannotated']
    return filtered_data

#%%
def train(dataset, checkpoint_dir):
    from trl import GRPOConfig, GRPOTrainer
    max_completion_length = max_seq_length//5-max_prompt_length # avoid long sequences

    training_args = GRPOConfig(
        learning_rate=5e-5,
        adam_beta1 = 0.9,
        adam_beta2 = 0.99,
        weight_decay = 0.1,
        warmup_ratio = 0.1,
        lr_scheduler_type = "cosine",
        optim = "paged_adamw_8bit",
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,  # Increase to 4 for smoother training
        num_generations=4,  # Decrease if out of memory
        max_prompt_length=max_prompt_length,
        max_completion_length=max_completion_length,
        # num_train_epochs = 1, # Set to 1 for a full training run
        max_steps=2000,
        save_steps=200,
        max_grad_norm=0.1,
        report_to="none",  # Can use Weights & Biases
        output_dir=checkpoint_dir,
        loss_type=args.loss_type,
        beta=0.0 if args.drop_kl else 0.04, # 0 if drop KL else default
        epsilon=args.grpo_epsilon,
        epsilon_high=args.clip_high,
        importance_sampling_level='sequence' if args.use_gspo else 'token',
    )
    reward_funcs = [
        xmlcount_reward_func,
        json_reward_func,
        correctness_reward_func,
    ]

    if args.reasoning_reward:
        reward_funcs += [
            reasoning_reward_func_relevancy,
            reasoning_reward_func_criteria,
            reasoning_reward_func_time,
        ]
        if args.full:
            reward_funcs += [
                reasoning_reward_func_diagnostic,
                reasoning_reward_func_exclusions,
                reasoning_reward_func_treatment,
            ]

    trainer = GRPOTrainer(
        model=model,
        processing_class=tokenizer,
        reward_funcs=reward_funcs,
        args=training_args,
        train_dataset=dataset,
    )
    trainer.train(resume_from_checkpoint=os.path.exists(checkpoint_dir) and bool(os.listdir(checkpoint_dir)))

def collate_fn(batch):
    batch_prompt = [item["prompt"] for item in batch]
    batch_answer = [item["answer"] for item in batch]
    return {"prompt": batch_prompt, "answer": batch_answer}

def compute_entropy(logprobs_lst):
    import torch
    # convert logprobs dict to tensor
    logprobs_values = torch.tensor(logprobs_lst, dtype=torch.float32)
    # convert to probabilities
    probs = torch.nn.functional.softmax(logprobs_values, dim=0)
    # compute entropy
    entropy = -torch.sum(probs * torch.log(probs+1e-12)) # avoid log(0)
    return entropy

def compute_avglogprob_and_entropy(tokens, logprobs):
    if not logprobs: # Logprobs not available
        return 0, 0
    if not isinstance(logprobs[0], dict): # {token_id: Logprob}
        raise Exception('Invalid type')
    logprobs = [
        next(iter(entry.values())).logprob if hasattr(next(iter(entry.values())), 'logprob') 
        else next(iter(entry.values()))
        for entry in logprobs
    ]
    entropies = [compute_entropy(entry) for entry in logprobs]
    avg_logprob = sum(logprobs) / len(logprobs)
    avg_entropy = sum(entropies) / len(entropies)
    return avg_logprob, avg_entropy

def inference(dataset):
    from vllm.lora.request import LoRARequest
    LORA_REQUEST_ID = 1
    sampling_params = load_sampling_params(args.grpo_base_model, args.use_deterministic, args.disable_thinking)
    batch_size = 16
    if not args.base:
        batch_size = 4 # unsloth native inference
    dataloader = DataLoader(
        dataset, batch_size=batch_size, shuffle=False, collate_fn=collate_fn
    )
    results, results_logprobs, results_perplexities, results_entropies = [], [], [], []
    import torch
    for batch in tqdm(dataloader):
        prompts = tokenizer.apply_chat_template(
            batch["prompt"], tokenize=False, add_generation_prompt=True, enable_thinking=not args.disable_thinking,
        )
        params = {'sampling_params': sampling_params}
        # Load LoRA adapters
        if model_save_path and not use_vllm and fast_inference: # unsloth VLLM fast inference
            params.update({'lora_request': model.load_lora(model_save_path)})
        elif model_save_path and use_vllm: # VLLM lora adapter
            params.update({'lora_request': LoRARequest(str(LORA_REQUEST_ID), LORA_REQUEST_ID, model_save_path)})
            LORA_REQUEST_ID += 1
        if not use_vllm and not fast_inference: # no unsloth VLLM, use OG tokenizer and generate
            inputs = tokenizer(prompts, padding=True, return_tensors='pt').to('cuda')
            prompts = tokenizer.batch_decode(inputs.input_ids, skip_special_tokens=True) # filter special tokens in prompt
            out = model.generate(
                **inputs,
                max_new_tokens=sampling_params.max_tokens,
                temperature=sampling_params.temperature,
                return_dict_in_generate=True,
                output_scores=True,
            )
            token_ids = out.sequences # shape: [batch_size, seq_len]
            logits = out.scores # list of tensors, each shape: [batch_size, vocab_size]
            out = tokenizer.batch_decode(token_ids, skip_special_tokens=True)
            out = [text[len(prompt):] for prompt, text in zip(prompts, out)]
            print(out[0])
            
            token_logprobs_lst = []
            start_idx = inputs.input_ids.shape[1]
            gen_len = len(logits)

            for b in range(len(prompts)):
                logprobs = []
                token_ids_gen = token_ids[b][start_idx:start_idx+gen_len]
                for step in range(gen_len):
                    step_logits = logits[step][b] # [vocab_size]
                    log_probs = torch.nn.functional.log_softmax(step_logits, dim=-1).cpu()
                    token_id = token_ids_gen[step]
                    logprobs.append({token_id.item(): log_probs[token_id].item()})
                token_logprobs_lst.append(logprobs)
            token_strs_lst = [tokenizer.convert_ids_to_tokens(seq[start_idx:start_idx+gen_len]) for seq in token_ids]
        else:
            out = model.generate(prompts, **params)
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
    if not use_vllm:
        from unsloth import FastLanguageModel, PatchFastRL
        PatchFastRL("GRPO", FastLanguageModel)
        os.environ['UNSLOTH_USE_MODELSCOPE'] = '1'
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=model_path,
            max_seq_length=max_seq_length,
            load_in_4bit=True,  # False for LoRA 16bit
            fast_inference=fast_inference,
            max_lora_rank=lora_rank,
            gpu_memory_utilization=0.7,  # Reduce if out of memory
            # local_files_only=True,
        )
        if not args.test:
            model = FastLanguageModel.get_peft_model(
                model,
                r=lora_rank,  # Choose any number > 0 ! Suggested 8, 16, 32, 64, 128
                target_modules=[
                    "q_proj",
                    "k_proj",
                    "v_proj",
                    "o_proj",
                    "gate_proj",
                    "up_proj",
                    "down_proj",
                ],  # Remove QKVO if out of memory
                lora_alpha=lora_rank,
                use_gradient_checkpointing="unsloth",  # Enable long context finetuning
                random_state=3407,
            )
        else:
            FastLanguageModel.for_inference(model)
    else:
        tensor_parallel_size = n_cuda
        if not args.base and not args.use_gspo:
            tensor_parallel_size *= 2
        from vllm import LLM
        params = {}
        if 'qwen3next' in args.grpo_base_model:
            params.update({
                'speculative_config': {
                    "method": "qwen3_next_mtp",
                    "num_speculative_tokens": 1,
                }
            })
        model = LLM(
            model=base_model_path,
            max_model_len=max_seq_length,
            gpu_memory_utilization=0.9,
            tensor_parallel_size=n_cuda,
            enforce_eager=True,
            enable_lora=not args.base,
            max_lora_rank=32 if not args.base else 16, # GRPO finetuned is 32
            **params
        )
        tokenizer = model.get_tokenizer()
    return model, tokenizer

def get_prompt_modules(v2_prompt):
    base = importlib.import_module("prompts.prompt")
    overrides = importlib.import_module("prompts.prompt_V2") if v2_prompt else None
    return base, overrides

def get_var(name, base_module, overrides_module):
    """Return variable from module overrides if defined, else from base."""
    if overrides_module and hasattr(overrides_module, name):
        return getattr(overrides_module, name)
    return getattr(base_module, name)

#%%
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--use_deterministic", action="store_true")
    parser.add_argument("--v2_prompt", action="store_true")
    parser.add_argument("--grpo_base_model", default="qwen3_8b", choices=list(MODELS.keys()))
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--test_full", action="store_true")
    parser.add_argument("--test_folder", type=str, default="sample658") # sample658, sledai-notes
    parser.add_argument("--sample_filter", type=str) # sample to include (e.g. sample242)
    parser.add_argument("--ckpt", type=int, default=2000)
    parser.add_argument("--base", action="store_true")
    parser.add_argument("--full", action="store_true") # full reasoning rewards
    parser.add_argument("--reasoning_reward", action="store_true")
    parser.add_argument("--ratio", type=float, default=1.0) # throw away unannotated & annotated NEGATIVE samples to reach certain ratio with POSITIVE samples
    parser.add_argument("--equal_correctness", action="store_true") # use equal value for positive vs negative sample in correctness reward
    parser.add_argument("--loss_type", default="bnpo", choices=["grpo", "dr_grpo", "bnpo"])
    parser.add_argument("--drop_kl", action="store_true")
    parser.add_argument("--grpo_epsilon", type=float, default=0.2) # GSPO is 3e-4
    parser.add_argument("--clip_high", type=float, default=None) # DAPO is 0.28, GSPO is 4e-4
    parser.add_argument("--use_gspo", action="store_true") # GSPO (sequence-level optimization)
    parser.add_argument("--n_run", type=int)
    parser.add_argument("--disable_thinking", action="store_true")
    parser.add_argument("--no_train_test_split", action="store_true")
    args = parser.parse_args()
    n_cuda = MODELS[args.grpo_base_model][1]
    use_vllm = args.test # use VLLM for inference
    base_model_path = MODELS[args.grpo_base_model][0]

    max_seq_length = 40960  # Can increase for longer reasoning traces
    lora_rank = 32  # Larger rank = smarter, but slower
    max_prompt_length = 3000
    fast_inference = not 'qwen3' in args.grpo_base_model # Qwen 3 RoPE Scaling not supported

    prefix = args.test_folder
    source_dir = f"data/{prefix}/"
    benchmark_csv = f"data/{prefix}_entities_gold.csv"
    scores_csv = f"data/{prefix}_scores_gold.csv"
    df_ben = pd.read_csv(benchmark_csv)
    df_ben = df_ben[df_ben.filename.isin(os.listdir(source_dir))]
    df_scores = pd.read_csv(scores_csv)

    base_module, overrides_module = get_prompt_modules(args.v2_prompt)
    score_template = get_var("score_template", base_module, overrides_module)
    output_template = get_var("output_template", base_module, overrides_module)

    score_template += output_template
    prompt_builder = init_prompt_builder(score_template)

    if not args.no_train_test_split and args.ratio:
        prefix += f"_ratio{args.ratio}"
    if args.v2_prompt:
        prefix += '_V2'
    dataset_save_root = "save/"
    os.makedirs(dataset_save_root, exist_ok=True)
    dataset_save_path = f"{dataset_save_root}/dataset_" + prefix
    suffix = prefix
    suffix += ("_nokl" if args.drop_kl else "")
    suffix += ("_equal" if args.equal_correctness and not args.base else "")
    suffix += ("_full" if args.full else "")
    suffix += ("_reasoning_reward" if args.reasoning_reward else "")
    suffix += ("_clip" if args.clip_high is not None else "")
    suffix += (f"_{args.loss_type.replace('_', '')}_loss" if args.loss_type != "grpo" and not args.base else "")
    suffix += ("_" + args.grpo_base_model)
    suffix += ("_gspo" if args.use_gspo else "")
    checkpoint_dir = f"save/outputs_" + suffix
    model_save_path = checkpoint_dir + f"/checkpoint-{args.ckpt}" if not args.base else ''

    if os.path.exists(dataset_save_path):
        dataset = DatasetDict.load_from_disk(dataset_save_path)
    else:
        train_pids, test_pids, full_pids, filtered_descriptors = split_pids(df_scores)
        save_split_pids_file = f'save/split_pids_{args.test_folder}.json'
        # use the same set of pids for all experiments
        if os.path.exists(save_split_pids_file):
            print('Using existing set of train/test pids...')
            with open(save_split_pids_file) as f:
                json_data = json.load(f)
            train_pids = json_data['train']
            test_pids = json_data['test']
        else:
            with open(save_split_pids_file, 'w') as f:
                json.dump({
                    'train': list(train_pids),
                    'test': list(test_pids),
                }, f)
        full_data = load_sle_data(full_pids)
        full_data = build_dataset(full_data, ratio=None, descriptors=descriptors, min_scored=0)
        if args.no_train_test_split:
            dataset = DatasetDict({
                "full": Dataset.from_list(full_data),
            })
        else:
            train_data = load_sle_data(train_pids)
            test_data = load_sle_data(test_pids)
            train_data = build_dataset(train_data, args.ratio, filtered_descriptors)
            test_data = build_dataset(test_data, None, filtered_descriptors) # test all data
            dataset = DatasetDict({
                "train": Dataset.from_list(train_data),
                "test": Dataset.from_list(test_data),
                "full": Dataset.from_list(full_data),
            })
            visualise_data(dataset['train'], f'annotation_{prefix.split("_")[0]}_distributions_{args.ratio}_train.png')
            visualise_data(dataset['test'], f'annotation_{prefix.split("_")[0]}_distributions_{args.ratio}_test.png')

        dataset.save_to_disk(dataset_save_path)
        visualise_data(dataset['full'], f'annotation_{prefix.split("_")[0]}_distributions.png')

    if not args.test:
        model, tokenizer = load_model_tokenizer(base_model_path)
        train(dataset["train"], checkpoint_dir)
    else:
        print("Beginning inference...")
        results_dir = 'results_grpo'
        results_dir += f'/{suffix.replace("_V2", "")}' + ('_nothink' if args.disable_thinking else '') + ('_base' if args.base else str(args.ckpt)) + f'{"_deterministic" if args.use_deterministic else ""}_{args.n_run}/'
        os.makedirs(results_dir, exist_ok=True)
        path_name = 'outputs'
        if args.v2_prompt:
            path_name += '_V2'
        pkl_path = results_dir+f'{path_name}.pkl'
        to_run_inference = True
        results_train, results_test = [], []
        data = None
        if os.path.exists(pkl_path):
            with open(pkl_path, 'rb') as f:
                data = pickle.load(f)
        if data and 'results_full' in data:
            results_full = data['results_full']
            answers_full = dataset['full']['answer']
            filenames_full = dataset['full']['filename']
            to_run_inference = False
        if data and not args.test_full:
            for split in ['test', 'train']:
                answers = dataset[split]['answer']
                filenames = dataset[split]['filename']
                locals()[f'answers_{split}'] = answers
                locals()[f'filenames_{split}'] = filenames
                if f'results_{split}' in data:
                    locals()[f'results_{split}'] = data[f'results_{split}']
                    to_run_inference = False # assume both splits exist
        if to_run_inference:
            model, tokenizer = load_model_tokenizer(model_save_path if args.test and not args.base and not use_vllm else base_model_path)
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
