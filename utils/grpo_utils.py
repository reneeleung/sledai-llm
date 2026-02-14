import asyncio
import demjson3 as demjson
import re
import numpy as np
import pandas as pd
import uuid
from prompts.prompt import descriptors, sledai_weights

SYSTEM_PROMPT = """
Respond in the following format:
<reasoning>
...
</reasoning>
<answer>
...
</answer>
"""

def extract_xml_answer(text: str) -> str:
    answer = text.rsplit("<answer>", 1)[-1]
    answer = answer.rsplit("</answer>", 1)[0]
    return answer.strip()

def init_prompt_builder(template):
    from haystack import Pipeline
    from haystack.components.builders.prompt_builder import PromptBuilder
    pipe = Pipeline()
    pipe.add_component('prompt_builder', PromptBuilder(template=template))
    return pipe

def get_template_from_prompt_builder(pipe):
    prompt_builder = pipe.get_component('prompt_builder')
    template = prompt_builder.to_dict()['init_parameters']['template']
    return template

def load_sampling_params(model_name, use_deterministic=False, disable_thinking=False):
    from vllm import SamplingParams
    if use_deterministic:
        return SamplingParams(
            temperature=0,
            top_k=50,
            top_p=0.95,
            min_p=0,
            max_tokens=4608,
            logprobs=20,            
        )
    if 'qwen' in model_name and disable_thinking:
        return SamplingParams(
            temperature=0.7,
            top_k=20,
            top_p=0.8,
            min_p=0,
            max_tokens=4608,
            logprobs=20,
        )
    elif 'qwen' in model_name:
        return SamplingParams(
            temperature=0.6,
            top_k=20,
            top_p=0.95,
            min_p=0,
            max_tokens=4608,
            logprobs=20,
        )
    elif 'phi' in model_name:
        return SamplingParams(
            temperature=0.8,
            top_k=50,
            top_p=0.95,
            max_tokens=4608*2,
        )
    return SamplingParams(
        temperature=1.0,
        top_k=0,
        top_p=1.0,
        min_p=0,
        max_tokens=4608*2,
        logprobs=20,
    )

def parse_output(output, is_lst=False):
    # jsonstr = output.split('</think>')[-1].split('</reasoning>')[-1].strip()
    jsonstr = output
    opening = r'\[' if is_lst else r'\{'
    closing = r'\]' if is_lst else r'\}'
    # Non-greedy match between opening and closing bracket, ignoring nested/quoted brackets
    pattern = rf'{opening}.*?{closing}'
    matches = re.findall(pattern, jsonstr, re.DOTALL)
    extracted = matches[-1] if matches else None
    def escape_apostophes(jsonstr):
        matches = re.findall(r":\s+'(.*?)'(?:\n|,\n)", jsonstr)
        for m in matches:
            jsonstr = jsonstr.replace(m, m.replace("'", ''))
        return jsonstr
    extracted = escape_apostophes(extracted)
    # extracted = re.sub(r"#.*", "", extracted) # remove comments
    extracted = extracted.replace(' True', ' true').replace(' False', ' false').replace(' None', ' null') # convert to JSON language
    return demjson.decode(extracted)

def build_scores_df(score_preds):
    df_scores_pred = pd.DataFrame(score_preds).transpose()
    df_scores_pred.reset_index(inplace=True)
    df_scores_pred.rename({'index': 'filename'}, axis=1, inplace=True)
    return df_scores_pred

def get_final_scores(df_scores):
    df_scores['final_score'] = df_scores.apply(lambda row: sum(row[descrip] * sledai_weights[descrip] for descrip in descriptors), axis=1)
    df_scores['final_score'] = df_scores['final_score'].fillna(0)
    return df_scores.final_score.tolist()

def compute_weights_of_misclassified(df_pred, df_gold):
    # Merge on filename to ensure alignment
    df_merged = df_pred.merge(df_gold, on='filename', suffixes=('_pred', '_gold'))
    df_merged = df_merged.sort_values(by='filename').reset_index(drop=True)
    weights_misclassified = []
    for _, row in df_merged.iterrows():
        total_weight = 0
        for descrip in descriptors:
            if row[f"{descrip}_pred"] != row[f"{descrip}_gold"]:
                total_weight += sledai_weights[descrip]
        weights_misclassified.append(total_weight)
    return weights_misclassified
