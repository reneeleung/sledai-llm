# Collect results and predict SLEDAI scores
import argparse
from datasets import DatasetDict
import pandas as pd
import pickle
from recipes import MODELS
from grpo import extract_xml_answer
from prompts.prompt import sledai_weights
from utils.grpo_utils import parse_output

def get_descrip_scores_across_runs(n_runs, llm_judge, grouped):
    ensemble_outputs = {}
    ensemble_outputs_judge = {}
    for i in range(n_runs):
        results_dir = results_dir_prefix + f'_{i+1}'
        with open(f'{results_dir}/outputs.pkl', 'rb') as f:
                results = pickle.load(f)
        if llm_judge:
            with open(f'{results_dir}/outputs{llm_judge}.pkl', 'rb') as f:
                results_judge = pickle.load(f)
        outputs = results['results_full']

        if llm_judge:
            outputs_judge = results_judge['results_full']
        for ans, o, f in zip(answers, outputs, filenames):
            if f not in ensemble_outputs:
                ensemble_outputs[f] = {}
                ensemble_outputs_judge[f] = {}
            try:
                parsed = parse_output(extract_xml_answer(o), is_lst=grouped)
            except Exception as e:
                parsed = [{'score': 0, 'confidence_score': 0, 'descriptor': a['descriptor']} for a in ans] if grouped else {'score': '0' , 'confidence_score': '0', 'descriptor': ans['descriptor']}
            if i not in ensemble_outputs[f]:
                ensemble_outputs[f][i] = {}
                ensemble_outputs_judge[f][i] = {}
            if not grouped:
                ans = [ans]
            for a in ans:
                ensemble_outputs[f][i][a['descriptor']] = parsed
        if llm_judge:
            for ans, o, f in zip(answers, outputs_judge, filenames):
                try:
                    parsed = parse_output(extract_xml_answer(o), is_lst=grouped)
                except Exception as e:
                    parsed = [{'score': None, 'confidence_score': None, 'descriptor': a['descriptor']} for a in ans] if grouped else {'score': None , 'confidence_score': None, 'descriptor': ans['descriptor']}
                if not grouped:
                    ans = [ans]
                for a in ans:
                    ensemble_outputs_judge[f][i][a['descriptor']] = parsed
    if grouped:
        descrips = set(a['descriptor'] for ans in answers for a in ans)
    else:
        descrips = set(a['descriptor'] for a in answers)
    descrips = list(descrips)
    return ensemble_outputs, ensemble_outputs_judge, descrips

def get_majority_scores(n_runs, llm_judge, grouped):
    vote_threshold = n_runs // 2 + 1
    score_preds = {}
    for ans, f, in zip(answers, filenames):
        if f not in score_preds:
            score_preds[f] = {}
        items = ans if grouped else [ans]
        for a in items:
            # collect scores from all runs
            scores = []
            for i in range(n_runs):
                parsed_list = ensemble_outputs[f][i][a['descriptor']]
                parsed_list = parsed_list if grouped else [parsed_list]
                score = 0
                try:
                    found = False
                    for entry in parsed_list:
                        score = int(entry['score'])
                        found = True
                        break
                    if not found:
                        for entry in parsed_list:
                            print(f, entry['descriptor'], a['descriptor'])
                except:
                    print('Unable to parse:', f)
                    print(parsed_list)
                scores.append(score)
            assert len(scores) == n_runs
            majority_score = int(sum(scores) >= vote_threshold)
            if llm_judge:
                scores_judge = []
                for i in range(n_runs):
                    parsed_list = ensemble_outputs_judge[f][i][a['descriptor']]
                    parsed_list = parsed_list if grouped else [parsed_list]
                    score_judge = None
                    try:
                        found = False
                        for entry in parsed_list:
                            if entry['descriptor'] not in descrips:
                                print(entry)
                            if entry['descriptor'] == a['descriptor']:
                                score_judge = int(entry['score'])
                                found = True
                                break
                        if not found:
                            for entry in parsed_list:
                                print('verified', f, entry['descriptor'], a['descriptor'])
                    except:
                        pass
                    scores_judge.append(score_judge)
                assert len(scores_judge) == n_runs
                for i in range(n_runs):
                    if scores_judge[i] is None:
                        scores_judge[i] = scores[i] # treat it as uncorrected if response not parsable
                majority_score_judge = int(sum(scores_judge) >= vote_threshold)
                majority_score = majority_score_judge
                scores = scores_judge
            score_preds[f][a['descriptor']] = majority_score
    return score_preds

def get_sledai():
    df_scores_pred = pd.DataFrame(score_preds).transpose()
    df_scores_pred.reset_index(inplace=True)
    df_scores_pred.rename({'index': 'filename'}, axis=1, inplace=True)
    df_scores_pred['final_score'] = df_scores_pred.apply(lambda row: sum(row[descrip] * sledai_weights[descrip] for descrip in descrips), axis=1)
    df_scores_pred['final_score'] = df_scores_pred['final_score'].fillna(0)
    return df_scores_pred


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_folder", type=str, default="sample_proof")
    parser.add_argument("--model_name", default="qwen3", choices=list(MODELS.keys()))
    parser.add_argument("--llm_judge", type=str, default="")
    parser.add_argument("--n_runs", type=int, default=5)
    parser.add_argument("--grouped", action="store_true")
    args = parser.parse_args()

    prefix = args.test_folder
    if args.grouped:
        prefix = "grouped_" + prefix
    source_dir = f"data/{prefix}/"
    dataset_save_path = "save/dataset_" + prefix
    dataset = DatasetDict.load_from_disk(dataset_save_path)
    answers = dataset['full']['answer']
    filenames = dataset['full']['filename']

    results_dir_prefix = f'results_inference/{prefix}_{args.model_name}'

    ensemble_outputs, ensemble_outputs_judge, descrips = get_descrip_scores_across_runs(args.n_runs, args.llm_judge, args.grouped)
    score_preds = get_majority_scores(args.n_runs, args.llm_judge, args.grouped)
    df_scores_pred = get_sledai()
    df_scores_pred.to_csv(f'{results_dir_prefix}_sledai_scores.csv', index=False)
