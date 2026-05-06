import os
import math
import pandas as pd
import plotly.express as px
import matplotlib.colors as mcolors
from matplotlib.lines import Line2D
import matplotlib.pyplot as plt
import numpy as np
import json
import pickle
import seaborn as sns
from datasets import DatasetDict
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    confusion_matrix,
    mean_squared_error,
    roc_curve,
    auc,
)
from prompts.prompt import type_a_hard, type_a_others, type_b, descriptors, sledai_weights, weights, TYPE_A, TYPE_B
from grpo import DIAGNOSTIC_DEFAULT
from utils.grpo_utils import extract_xml_answer, parse_output, build_scores_df, get_final_scores, compute_weights_of_misclassified

priority_names = ['total', 'type_b', 'type_a<8', 'type_a=8', 'weight=4', 'weight=2', 'weight=1'] + descriptors

# prefix = 'sample658'
# ratio = 1.0

prefix = 'sledai-notes'
ratio = None # if no_train_test_split
v2_prompt = False

grouped = False
n_runs = 5
# model = 'qwen3'
# model = 'qwen3_nothink'
model = 'gptoss_120b'
# model = 'llama3'
# model = 'r1qwen3_8b'
# model = 'qwen3_14b'

llm_judge = ''
# llm_judge = '_verified_gptoss_120b'

# sample = 'test'
sample = 'full'

scores_csv = f"data/{prefix}_scores_gold.csv"
df_scores_gold = pd.read_csv(scores_csv)

if ratio:
    prefix += f'_ratio{ratio}'

if grouped:
    prefix = 'grouped_' + prefix

## FOR PRETRAINED BASE MODELS
results_dir_prefix = f'{prefix}_{model}_base'

## FOR GRPO CHECKPOINTS
ckpt = 1200
# results_dir_prefix = f'{prefix}_nokl_equal_reasoning_reward_clip_{model}_gspo{ckpt}'

if n_runs == 1:
    results_dir_prefix += '_deterministic'

if llm_judge:
    conf_threshold = 5

dataset_save_path = f'save/dataset_{prefix}{"_V2" if v2_prompt else ""}/'
dataset = DatasetDict.load_from_disk(dataset_save_path)
ensemble_outputs = {}
ensemble_outputs_judge = {}

# 1. evaluate "average" performance using majority voting (create a {results_dir_prefix}_5runs_avg png)
# 2. analyse confidence scores
#    (a) "logit"-based confidence score vs mean accuracy: k/n times majority vote - is the majority vote correct (split analysis prediction 1 vs 0)?
#    (b) output model confidence score vs mean accuracy: mean confidence of those == majority vote - is the majority vote correct (split analysis prediction 1 vs 0)?
#    (c) stability (variance) of model confidence scores over 5 runs
for i in range(n_runs):
    unparsable = 0
    results_dir = results_dir_prefix + f'_{i+1}'
    path_name = 'outputs'
    if v2_prompt:
        path_name += '_V2'
    if os.path.exists(f'results_grpo/{results_dir}/{path_name}.json'):
        with open(f'results_grpo/{results_dir}/{path_name}.json') as f:
            results = json.load(f)
    else:
        with open(f'results_grpo/{results_dir}/{path_name}.pkl', 'rb') as f:
            results = pickle.load(f)
    if llm_judge:
        with open(f'results_grpo/{results_dir}/{path_name}{llm_judge}.pkl', 'rb') as f:
            results_judge = pickle.load(f)

    if f'results_{sample}' not in results and sample in ['train', 'test']:
        # filter 'train' or 'test' from 'full'
        results_full = results['results_full']
        answers = dataset[sample]['answer']
        filenames = dataset[sample]['filename']
        answers_full = dataset['full']['answer']
        filenames_full = dataset['full']['filename']
        if grouped:
            # file is unique in grouped prompt
            lookup = { (f, ','.join(sorted(a['descriptor'] for a in ans))): r for f, ans, r in zip(filenames_full, answers_full, results_full) }
            outputs = [ lookup[(f, ','.join(sorted(a['descriptor'] for a in ans)))] for f, ans in zip(filenames, answers) ]
            if llm_judge:
                results_judge_full = results_judge['results_full']
                lookup = { (f, ','.join(sorted(a['descriptor'] for a in ans))): r for f, ans, r in zip(filenames_full, answers_full, results_judge_full) }
                outputs_judge = [ lookup[(f, ','.join(sorted(a['descriptor'] for a in ans)))] for f, ans in zip(filenames, answers) ]
        else:
            lookup = { (f, a['descriptor']): r for f, a, r in zip(filenames_full, answers_full, results_full) }
            outputs = [ lookup[(f, a['descriptor'])] for f, a in zip(filenames, answers) ]
            if llm_judge:
                results_judge_full = results_judge['results_full']
                lookup = { (f, a['descriptor']): r for f, a, r in zip(filenames_full, answers_full, results_judge_full) }
                outputs_judge = [ lookup[(f, a['descriptor'])] for f, a in zip(filenames, answers) ]
    elif f'results_{sample}' in results:
        outputs = results[f'results_{sample}']
        # logprobs = results[f'results_logprobs_{sample}']
        # perplexities = results[f'results_perplexities_{sample}']
        answers = dataset[sample]['answer']
        filenames = dataset[sample]['filename']
        if llm_judge:
            outputs_judge = results_judge[f'results_{sample}']
    else:
        print('Unknown sample')
        exit()
    for ans, o, f in zip(answers, outputs, filenames):
        if f not in ensemble_outputs:
            ensemble_outputs[f] = {}
            ensemble_outputs_judge[f] = {}
        try:
            parsed = parse_output(extract_xml_answer(o), is_lst=grouped)
        except Exception as e:
            unparsable += 1
            parsed = [{'score': 0, 'confidence_score': 0, 'descriptor': a['descriptor']} for a in ans] if grouped else {'score': '0' , 'confidence_score': '0', 'descriptor': ans['descriptor']}
        if i not in ensemble_outputs[f]:
            ensemble_outputs[f][i] = {}
            ensemble_outputs_judge[f][i] = {}
        if not grouped:
            ans = [ans]
        for a in ans:
            ensemble_outputs[f][i][a['descriptor']] = parsed
    print(f'# unparsable (run={i+1}):', unparsable)
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

df_scores_gold = df_scores_gold[df_scores_gold.filename.isin(set(filenames))]

performance_file = f'results_grpo_summary/{results_dir_prefix}_{sample}/performance.txt'

if grouped:
    descrips = set(a['descriptor'] for ans in answers for a in ans)
else:
    descrips = set(a['descriptor'] for a in answers)
descrips = list(descrips)

def should_include(descrip_type, a):
    return (
        descrip_type == 'total' or
        (descrip_type == 'type_b' and a['descriptor'] in type_b) or
        (descrip_type == 'type_a<8' and a['descriptor'] in type_a_others) or
        (descrip_type == 'type_a=8' and a['descriptor'] in type_a_hard) or
        (descrip_type == 'weight=4' and sledai_weights[a['descriptor']] == 4) or
        (descrip_type == 'weight=2' and sledai_weights[a['descriptor']] == 2) or
        (descrip_type == 'weight=1' and sledai_weights[a['descriptor']] == 1) or
        a['descriptor'] == descrip_type
    )


def plot_roc_curves_by_descrip(descrip_roc_dict, save_name):
    fig, axes = plt.subplots(8, 3, figsize=(15, 24))  # 8 rows × 3 cols
    axes = axes.flatten()
    for i, descrip in enumerate(descriptors):
        ax = axes[i]
        fpr, tpr, roc_auc = descrip_roc_dict[descrip]
            # Plot ROC curve
        ax.plot(fpr, tpr, color="blue", lw=2, label=f"AUC = {roc_auc:.2f}")
        ax.fill_between(fpr, 0, tpr, color="blue", alpha=0.1)
        ax.plot([0, 1], [0, 1], color="gray", lw=1, linestyle="--")
        
        # Formatting
        ax.set_xlim([0.0, 1.0])
        ax.set_ylim([0.0, 1.05])
        ax.set_title(descrip, fontsize=10)
        ax.legend(loc="lower right", fontsize=8)
        ax.tick_params(labelsize=8)
    fig.tight_layout()
    plt.savefig(save_name)

def merge_confidence(logit_conf, maj_avg_conf, min_avg_conf, maj_std, min_std, epsilon=1e-6):
    if np.isnan(min_avg_conf):
        return maj_avg_conf
    return 10 * maj_avg_conf / (maj_avg_conf + min_avg_conf)

def evaluate_average_performance_by_descriptor(descrip_types, file):
    ner_preds, score_preds, confidences = {}, {}, {}
    descrip_pres, descrip_recs, descrip_f1s = [], [], []
    plot_data = []
    descrip_f1_dict, descrip_roc_dict = {}, {}
    for descrip_type in descrip_types:
        for vote_threshold in range(1,n_runs+1):
            n_verifier = 0
            y_true, y_pred, logit_confs, model_confs, model_confs_std, model_confs_minor, model_confs_minor_std = [], [], [], [], [], [], []
            ner_true, ner_pred = [], []
            # lp_confs, perp_confs = [], []
            y_descrips = []
            for ans, f, in zip(answers, filenames):
                if f not in ner_preds:
                    ner_preds[f] = {}
                if f not in score_preds:
                    score_preds[f] = {}
                if f not in confidences:
                    confidences[f] = {}
                items = ans if grouped else [ans]
                for a in items:
                    if not should_include(descrip_type, a):
                        continue
                    # collect scores from all runs
                    scores, model_confidences = [], []
                    ner_scores = []
                    for i in range(n_runs):
                        parsed_list = ensemble_outputs[f][i][a['descriptor']]
                        parsed_list = parsed_list if grouped else [parsed_list]
                        score, conf_score, ner_score = 0, 0, 0
                        try:
                            found = False
                            for entry in parsed_list:
                                if entry['descriptor'] == a['descriptor']:
                                    score = int(entry['score'])
                                    conf_score = int(entry['confidence_score']) if 'confidence_score' in entry else 0
                                    ner_score = int(str(entry['relevant']).lower() == 'true')
                                    found = True
                                    break
                            if not found:
                                for entry in parsed_list:
                                    print(f, entry['descriptor'], a['descriptor'])
                        except:
                            print('Unable to parse:', f)
                            print(parsed_list)
                        scores.append(score)
                        model_confidences.append(conf_score)
                        ner_scores.append(ner_score)
                    assert len(scores) == n_runs
                    assert len(ner_scores) == n_runs
                    majority_score = int(scores.count(1) >= vote_threshold) # majority vote
                    agreement = scores.count(majority_score)
                    logit_conf = round(agreement / n_runs, 2) # % of runs that agree with majority
                    majority_ner = int(sum(ner_scores) >= vote_threshold)
                    majority_confs = [conf for score, conf in zip(scores, model_confidences) if score == majority_score]
                    minority_confs = [conf for score, conf in zip(scores, model_confidences) if score != majority_score]
                    maj_avg_conf = np.mean(majority_confs)
                    min_avg_conf = np.mean(minority_confs)
                    maj_std = np.std(majority_confs)
                    min_std = np.std(minority_confs)
                    merged_conf = merge_confidence(logit_conf, maj_avg_conf, min_avg_conf, maj_std, min_std)
                    if llm_judge:
                        scores_judge, model_confidences_judge = [], []
                        ner_scores_judge = []
                        for i in range(n_runs):
                            parsed_list = ensemble_outputs_judge[f][i][a['descriptor']]
                            parsed_list = parsed_list if grouped else [parsed_list]
                            score_judge, conf_score_judge, ner_score_judge = None, None, None
                            try:
                                assert len(parsed_list) >= 1 # otherwise append None and use layer 1 results
                                found = False
                                for entry in parsed_list:
                                    if entry['descriptor'] == a['descriptor']:
                                        score_judge = int(entry['score'])
                                        conf_score_judge = int(entry['confidence_score']) if 'confidence_score' in entry else 0
                                        ner_score_judge = int(str(entry['relevant']).lower() == 'true')
                                        found = True
                                        break
                                if not found:
                                    for entry in parsed_list:
                                        print('verified', f, entry['descriptor'], a['descriptor'])
                            except:
                                pass
                            scores_judge.append(score_judge)
                            model_confidences_judge.append(conf_score_judge)
                            ner_scores_judge.append(ner_score_judge)
                        assert len(scores_judge) == n_runs
                        for i in range(n_runs):
                            if scores_judge[i] is None:
                                scores_judge[i] = scores[i] # treat it as uncorrected if response not parsable
                            if model_confidences_judge[i] is None:
                                model_confidences_judge[i] = model_confidences[i]
                            if ner_scores_judge[i] is None:
                                ner_scores_judge[i] = ner_scores[i]
                        majority_score_judge = int(scores_judge.count(1) >= vote_threshold)
                        majority_ner_judge =int(sum(ner_scores_judge) >= vote_threshold)
                        # update to use second layer as final outputs
                        # only use verifier result if first layer confidence < threshold
                        if majority_ner and merged_conf <= conf_threshold:
                            n_verifier += 1
                            majority_score = majority_score_judge
                            agreement = scores_judge.count(majority_score)
                            logit_conf = round(agreement / n_runs, 2)
                            scores = scores_judge
                            model_confidences = model_confidences_judge
                            majority_ner = majority_ner_judge

                    # Filter confidences that match the majority score
                    majority_confidences = [conf for score, conf in zip(scores, model_confidences) if score == majority_score]
                    minority_confidences = [conf for score, conf in zip(scores, model_confidences) if score != majority_score]
                    y_true.append(int(a['score']))
                    y_pred.append(majority_score)
                    logit_confs.append(logit_conf)
                    model_confs.append(np.mean(majority_confidences))
                    model_confs_std.append(np.std(majority_confidences))
                    model_confs_minor.append(np.mean(minority_confidences))
                    model_confs_minor_std.append(np.std(minority_confidences))
                    ner_true.append(int(a['diagnostic'] != DIAGNOSTIC_DEFAULT))
                    ner_pred.append(majority_ner)
                    y_descrips.append(a['descriptor'])
                    if vote_threshold == (n_runs // 2 + 1):
                        ner_preds[f][a['descriptor']] = majority_ner
                        score_preds[f][a['descriptor']] = majority_score
                        confidences[f][a['descriptor']] = merge_confidence(logit_confs[-1], model_confs[-1], model_confs_minor[-1], model_confs_std[-1], model_confs_minor_std[-1])
            acc = accuracy_score(y_true, y_pred)
            pre = precision_score(y_true, y_pred, zero_division=np.nan)
            rec = recall_score(y_true, y_pred, zero_division=np.nan)
            f1 = f1_score(y_true, y_pred, zero_division=np.nan)
            tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0,1]).ravel().tolist()
            plot_data.extend([
                {'Descriptor': descrip_type, 'Votes': vote_threshold, 'Metric': 'F1', 'Score': f1, '# predicted 1s': sum(y_pred)}
            ])
            if vote_threshold == (n_runs // 2 + 1):
                if descrip_type == 'total':
                    print(f'\n\nVerifier reruns: {n_verifier/len(y_true)*100:.1f}\n\n')
                fpr, tpr, _ = roc_curve(y_true, y_pred)
                roc_auc = auc(fpr, tpr)
                print(f'{sample} {descrip_type}\tscore acc: {acc}\tprecision: {pre}\trecall: {rec}\tF1: {f1}\tAUROC: {roc_auc}', file=file)
                print(f'{sample} {descrip_type}\tscore total samples: {len(y_true)}\tTN: {tn}\tFP: {fp}\tFN: {fn}\tTP: {tp}', file=file)
                if descrip_type in descrips:
                    descrip_pres.append(pre)
                    descrip_recs.append(rec)
                    descrip_f1s.append(f1)
                    descrip_f1_dict[descrip_type] = f1
                    descrip_roc_dict[descrip_type] = (fpr, tpr, roc_auc)

                acc = accuracy_score(ner_true, ner_pred)
                pre = precision_score(ner_true, ner_pred, zero_division=np.nan)
                rec = recall_score(ner_true, ner_pred, zero_division=np.nan)
                f1 = f1_score(ner_true, ner_pred, zero_division=np.nan)
                tn, fp, fn, tp = confusion_matrix(ner_true, ner_pred, labels=[0,1]).ravel().tolist()
                print(f'{sample} {descrip_type}\trelevancy acc: {acc}\tprecision: {pre}\trecall: {rec}\tF1: {f1}', file=file)
                print(f'{sample} {descrip_type}\trelevancy total samples: {len(ner_true)}\tTN: {tn}\tFP: {fp}\tFN: {fn}\tTP: {tp}', file=file)

    macro_pre = np.nanmean(descrip_pres)
    macro_rec = np.nanmean(descrip_recs)
    macro_f1 = np.nanmean(descrip_f1s)
    print(f'{sample} total_macro\tscore\tprecision: {macro_pre}\trecall: {macro_rec}\tF1: {macro_f1}', file=file)

    # Interactive plot
    df = pd.DataFrame(plot_data)
    df['Descriptor'] = pd.Categorical(df['Descriptor'], categories=priority_names, ordered=True)
    df = df.sort_values(['Descriptor', 'Votes', 'Metric'])
    fig = px.line(df, x='Votes', y='Score', color='Descriptor', line_dash='Metric',
                title='Performance Metrics by Descriptor and Vote Threshold',
                markers=True,
                hover_data={'# predicted 1s': True})

    fig.update_layout(legend_title='Descriptor / Metric',
                    xaxis_title='Vote Threshold',
                    yaxis_title='Micro-F1',
                    hovermode='x unified')
    fig.write_html(f"{model_summary_dir}/{results_dir_prefix}_{sample}{llm_judge}.html")

    # ROC curves
    plot_roc_curves_by_descrip(descrip_roc_dict, f"{model_summary_dir}/{results_dir_prefix}_{sample}{llm_judge}_roc.png")

    return ner_preds, score_preds, confidences

model_summary_dir = 'model_performance_summary'
os.makedirs(model_summary_dir, exist_ok=True)

os.makedirs(os.path.dirname(performance_file), exist_ok=True)
with open(performance_file, 'w') as f:
    ner_preds, score_preds, confidences = evaluate_average_performance_by_descriptor({'total', 'type_b', 'type_a<8', 'type_a=8', 'weight=4', 'weight=2', 'weight=1'}.union(descrips), f)


########## model performance #############
def plot_heatmap_by_descrip(df, save_name):
    weights_df = pd.DataFrame(weights, columns=["descriptor","weight","type"])

    # Map group
    def assign_group(row):
        if row["type"] == TYPE_A:
            return "Type A"
        return "Type B"

    weights_df["group"] = weights_df.apply(assign_group, axis=1)
    # Add extra rows at the top
    extra_rows = pd.DataFrame([["total", None, None, "Total"],
                               ["type_b", None, None, "Total"],
                               ["type_a<8", None, None, "Total"],
                               ["type_a=8", 8, None, "Total"],
                               ["weight=4", 4, None, "Total"],
                               ["weight=2", 2, None, "Total"],
                               ["weight=1", 1, None, "Total"]], columns=["descriptor","weight","type","group"])
    weights_df = pd.concat([extra_rows, weights_df], ignore_index=True)

    # Merge with your df
    df_filtered = df.reset_index().rename(columns={"index": "descriptor"}).merge(weights_df, on="descriptor")

    # Calculate positive %
    df_filtered["Positive samples"] = pd.to_numeric(df_filtered["# positive samples"], errors="coerce")
    df_filtered["Relevant samples"] = pd.to_numeric(df_filtered["# relevant samples"], errors="coerce")

    # Build heatmap matrix
    metrics = ["score F1","score precision","score recall","score auroc"]
    context = ["Positive samples","Relevant samples","weight"]
    heatmap_data = df_filtered[metrics+context].apply(pd.to_numeric, errors="coerce") # convert strings to numbers
    heatmap_data.index = df_filtered["descriptor"]

    # Plot heatmap
    fig, ax = plt.subplots(figsize=(13, 0.6*len(heatmap_data)))

    norm = mcolors.Normalize(vmin=0,vmax=100)
    cmap_perf = mcolors.LinearSegmentedColormap.from_list("journal_blue", ["white", "#925E9FFF"])
    cmap_perf.set_bad("lightgray")   # distinguish NaN values clearly
    context_colors = ["#FDAF91FF", "#FDAF91FF", "#ADB6B6FF"]

    # Draw cells
    for i, desc in enumerate(heatmap_data.index):
        for j, col in enumerate(heatmap_data.columns):
            val = heatmap_data.iloc[i,j]
            if col in metrics:
                if pd.isna(val):
                    color = cmap_perf(np.nan)
                    label = "NaN"
                    text_color = "black"
                else:
                    val *= 100
                    color = cmap_perf(norm(val))
                    text_color = "white" if norm(val) > 0.6 else "black"
                    label = "100" if val == 100 else f"{val:.1f}"
            else:
                color = context_colors[j - len(metrics)]
                text_color = "black"
                label = "-" if pd.isna(val) else f"{int(val)}"
            ax.add_patch(plt.Rectangle((j,i),1,1,color=color))
            ax.text(j+0.5,i+0.5,label,ha="center",va="center",color=text_color,fontsize=16)

    # Grid lines
    for x in range(len(metrics + context) + 1):
        ax.axvline(x, color='white', lw=1)
    for y in range(len(heatmap_data) + 1):
        ax.axhline(y, color='white', lw=1)

    # Labels
    ax.margins(x=0, y=0)
    ax.set_xticks(np.arange(len(metrics + context)) + 0.5)
    ax.set_xticklabels(["F1-score","Precision","Recall","AUROC","Positive samples","Relevant samples","SLEDAI-2K Weight"],
                        rotation=45, ha="right", fontsize=18)
    ax.set_yticks(np.arange(len(heatmap_data)) + 0.5)
    ax.set_yticklabels(heatmap_data.index, fontsize=18)
    ax.set_ylabel("Descriptor", fontsize=18, fontweight="bold")
    ax.invert_yaxis()

    # Map descriptor -> group
    desc_to_group = dict(zip(df_filtered["descriptor"], df_filtered["group"]))

    color_map = {
        "Type A": (83/255, 120/255, 167/255),   # RGB for Type A
        "Type B": (224/255, 85/255, 78/255),    # RGB for Type B
        "Total": "black"
    }

    # Apply colors to ytick labels
    for tick in ax.get_yticklabels():
        desc = tick.get_text()
        grp = desc_to_group.get(desc, "Type A")
        tick.set_color(color_map[grp])

    # Legend explaining label colors
    handles = [
        Line2D([0], [0], color=color_map["Type A"], lw=8, label="Type A"),
        Line2D([0], [0], color=color_map["Type B"], lw=8, label="Type B"),
    ]
    ax.legend(handles=handles,
            loc="upper left",
            bbox_to_anchor=(-0.35, 1.02),   # shift left of y-axis labels
            frameon=False,
            title="Descriptor type",
            fontsize=16,
            title_fontsize=17)

    # Colorbar for performance metrics
    sm = plt.cm.ScalarMappable(cmap=cmap_perf,norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm,ax=ax,fraction=0.03,pad=0.04,shrink=2)
    cbar.set_label("Performance metrics",fontsize=16)
    cbar.ax.tick_params(labelsize=14)

    plt.tight_layout()
    plt.savefig(save_name,bbox_inches="tight")


def parse_metric(metric, convert=True):
    if not metric:
        return None
    try:
        metric = float(metric.split(':')[1])
    except (IndexError, ValueError):
        metric = np.nan
    return f'{metric:.3f}' if convert else metric

results = {}
with open(performance_file) as f:
    lines = f.readlines()
for l in lines:
    descrip, r = l.split('\t', 1)
    if not descrip.startswith(sample):
        continue
    dataset, descrip = descrip.split()
    if descrip not in results:
        results[descrip] = {}
    if 'total samples' in r:
        total, tn, fp, fn, tp = r.split('\t')
        if r.startswith('relevancy'):
            results[descrip]['# relevant samples'] = str(int(parse_metric(tp, convert=False))+int(parse_metric(fn, convert=False)))
        elif r.startswith('score'):
            results[descrip]['# positive samples'] = str(int(parse_metric(tp, convert=False))+int(parse_metric(fn, convert=False)))
        continue
    r = r.strip().split('\t')
    if descrip == 'total_macro' and len(results[descrip]) == 0:
        _, prec, rec, f1 = r
        results[descrip]['score precision'] = parse_metric(prec)
        results[descrip]['score recall'] = parse_metric(rec)
        results[descrip]['score F1'] = parse_metric(f1)
    elif len(r) == 5:
        acc, prec, rec, f1, auroc = r
        results[descrip]['score auroc'] = parse_metric(auroc)
        results[descrip]['score precision'] = parse_metric(prec)
        results[descrip]['score recall'] = parse_metric(rec)
        results[descrip]['score F1'] = parse_metric(f1)
    elif len(r) == 4:
        acc, prec, rec, f1 = r
        print(f'{descrip} NER F1:', parse_metric(f1))

df = pd.DataFrame(results).transpose()

# move rows to top
top_rows = df[df.index.isin(priority_names)].loc[priority_names]
bot_rows = df[~df.index.isin(priority_names)]
df = pd.concat([top_rows, bot_rows])

# generate heatmap
plot_heatmap_by_descrip(df, f"{model_summary_dir}/{results_dir_prefix}_{sample}{llm_judge}_heatmap.png")

########### evaluate final score ############
def evaluate_final_score():
    df_ner_pred = build_scores_df(ner_preds)
    df_scores_pred = build_scores_df(score_preds)
    df_confidences_pred = build_scores_df(confidences)
    df_scores_gold_filtered = df_scores_gold[df_scores_gold["filename"].isin(df_scores_pred.filename.tolist())]

    df_ner_pred.sort_values(by='filename', inplace=True)
    df_scores_pred.sort_values(by='filename', inplace=True)
    df_scores_gold_filtered.sort_values(by='filename', inplace=True)
    assert df_scores_gold_filtered.filename.tolist() == df_scores_pred.filename.tolist()
    scores_true = get_final_scores(df_scores_gold_filtered)
    scores_pred = get_final_scores(df_scores_pred)

    df_scores_pred.to_csv(f'results_grpo/{results_dir_prefix}{llm_judge}{"" if sample == "full" else ("_"+sample)}.csv', index=False)

    # Compute average confidence per sample based on relevant predictions
    avg_confidences = []
    for i, row in df_ner_pred.iterrows():
        pred_values = row[descriptors]
        conf_values = df_confidences_pred.loc[i, descriptors]
        wts = np.array([sledai_weights[d] for d in descriptors])
        # Mask for "relevant" predictions
        positive_mask = pred_values > 0
        if positive_mask.any():
            avg_conf = conf_values[positive_mask].mean()
        else:
            avg_conf = conf_values.mean()
        avg_confidences.append(avg_conf)

    mse = mean_squared_error(scores_true, scores_pred)
    # compute total weight of misclassified decsriptors
    weights_misclassified = compute_weights_of_misclassified(df_scores_pred, df_scores_gold_filtered)
    exact_matches = sum(w==0 for w in weights_misclassified)
    within_tolerance1 = sum(w<=1 for w in weights_misclassified)
    within_tolerance2 = sum(w<=2 for w in weights_misclassified)
    total_files = len(scores_true)
    exact_match_percentage = exact_matches / total_files * 100
    within_tolerance_percentage1 = within_tolerance1 / total_files * 100
    within_tolerance_percentage2 = within_tolerance2 / total_files * 100

    print(f"Score equal: {sum(t==p for t, p in zip(scores_true, scores_pred))}")
    print(f"Exact Matches: {exact_matches}/{total_files} ({exact_match_percentage:.0f}%)")
    print(f"<=1 tolerance: {within_tolerance1}/{total_files} ({within_tolerance_percentage1:.0f}%)")
    print(f"<=2 tolerance: {within_tolerance2}/{total_files} ({within_tolerance_percentage2:.0f}%)")
    print('RMSE:', np.sqrt(mse))

    ### Errors plot ###
    predictions = scores_pred
    ground_truths = scores_true
    errors = np.array(predictions) - np.array(ground_truths)

    # Set up canvas
    fig, ax1 = plt.subplots(figsize=(8, 6))
    ax1.set_xticklabels(["Prediction Quality"])
    ax1.set_xlim(-0.5, 1.5)
    # Second axis for error distribution
    ax2 = ax1
    sns.violinplot(y=errors, ax=ax2, color="lightblue", inner="quartile", width=0.5)
    ax2.set_ylabel("Prediction Error (Pred - Truth)")
    # Annotation
    ax1.set_title(f"Prediction Error Distribution\n{model}{'+'+llm_judge if llm_judge else ''}")
    ax1.legend(loc="upper right")
    plt.tight_layout()
    plt.savefig(f"{model_summary_dir}/{results_dir_prefix}_{sample}_finalscore{llm_judge}.png")

    ### Scatter plot ###
    df_plot = pd.DataFrame({
        'truth': scores_true,
        'pred': scores_pred,
        'confidence': avg_confidences,
    })
    # Group by (truth, pred) to aggregate samples
    grouped = df_plot.groupby(['truth', 'pred']).agg(
        count=('confidence', 'size'),
        avg_conf=('confidence', 'mean')
    ).reset_index()
    # Normalize count to get proportion
    grouped['proportion'] = grouped['count'] / grouped['count'].sum()
    scaled_sizes = np.sqrt(grouped['count']) * 40

    plt.figure(figsize=(8, 6))
    min_conf = grouped["avg_conf"].min()
    # norm = mcolors.Normalize(vmin=math.floor(min_conf), vmax=10)
    norm = mcolors.Normalize(vmin=7, vmax=10)
    scatter = plt.scatter(
        grouped['truth'],
        grouped['pred'],
        s=scaled_sizes,
        c=grouped['avg_conf'],
        cmap='viridis',
        norm=norm,
        alpha=0.8,
        edgecolors='k',
        zorder=3
    )

    # Bubble size legend
    min_count = grouped['count'].min()
    top_three = grouped['count'].nlargest(3)
    max_count = top_three.iloc[0]
    second_largest = top_three.iloc[1]
    third_largest = top_three.iloc[2]
    legend_counts = [min_count, third_largest, second_largest, max_count]
    legend_sizes = [np.sqrt(c) * 40 for c in legend_counts]

    for count, size in zip(legend_counts, legend_sizes):
        plt.scatter([], [], s=size, c='gray', alpha=0.6, edgecolors='k',
                    label=f'{count} report{"s" if count > 1 else ""}')
    plt.legend(loc='upper left', frameon=True)

    # Ideal diagonal line
    x_min = min(min(scores_true), min(scores_pred))
    x_max = max(max(scores_true), max(scores_pred))
    x_vals = np.array([x_min, x_max])
    plt.plot(x_vals, x_vals, 'r--', label='Ideal Prediction', zorder=2)

    # Add deviation bands
    deviation_colors = sns.color_palette('plasma', 3)
    alphas = [0.25, 0.18, 0.12] # progressively lighter
    for i, delta in enumerate([2, 4, 8]):
        plt.fill_between(x_vals, x_vals - delta, x_vals + delta, color=deviation_colors[i], alpha=alphas[i], zorder=1, label=f'±{delta}')       # Upper and lower bounds
    # Labels, title, colorbar
    plt.xlabel('Ground Truth Scores', fontsize=12)
    plt.ylabel('Predicted Scores', fontsize=12)
    plt.title('Predicted vs Ground Truth Scores', fontsize=14)
    cbar = plt.colorbar(scatter)
    cbar.set_label('Average Model Confidence', fontsize=11)

    # Add grid lines
    plt.grid(True, linestyle='--', alpha=0.6)

    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{model_summary_dir}/{results_dir_prefix}_{sample}_finalscore_scatter{llm_judge}.png")

evaluate_final_score()
