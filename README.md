# SLEDAI-LLM
Automated SLEDAI-2K scoring from clinical notes using large language models (LLMs).

## Dataset
Our study includes hospital clinical notes, synthetic cases derived from published case reports, and MIMIC-IV discharge notes. The hospital data cannot be shared publicly due to patient privacy safeguards. However, the synthetic cases are available on [Zenodo](https://doi.org/10.5281/zenodo.20042444).

## Getting started
1. Install dependencies
```
pip install -r requirements.txt
```

2. Access the data
- Download the annotated data via Zenodo.
- Place the notes (.txt) and the annotations (.ann) in a folder under `data/`, (e.g. `data/sledai-notes/`).
- Create annotated csv files.
```
cd data/
python brat_to_csv.py
```

3. Run inference

In `recipes.py`, you may set the number of GPUs required to run the LLM. For example, GPT-OSS-120b requires 2xL40Ss, or 4x4090s.

The following script runs inference on the full set. To only run on the test set, remove `--test_full`.
```
python grpo.py --grpo_base_model gptoss_120b --test --base --test_full --test_folder sledai-notes --no_train_test_split --n_run 1
```

For grouped descriptors prompt, run the following:
```
python grpo_grouped.py --grpo_base_model gptoss_120b --test --base --test_full --test_folder sample658 --n_run 1
```

**Note**: If you are running inference across different machines, make sure to use the same `save/dataset_*` or `save/dataset_grouped_*` to ensure the order of prompts is the same for the train/test data.

4. Second-layer verifier

To following runs the second-layer verifier based on outputs of the first layer.
```
python grpo_verifier.py --model_to_check gptoss_120b --test_full --test_folder sledai-notes --n_run 1
``` 

5. Summarize results

After inference of `k` runs (e.g. `k=5`), we can evaluate the performance. You may configure within the file (e.g. model name, individual vs grouped, one vs two layers, dataset name, etc.)
```
python summarise_model_performance.py
```

6. Finetuning models

The following finetunes Qwen3-14B using GSPO. Replace sample658 with your own data. You will need a comprehensive dataset covering all descriptors.
```
python grpo.py --grpo_base_model qwen3_14b --use_gspo --drop_kl --reasoning_reward --equal_correctness --loss_type grpo --grpo_epsilon 3e-4 --clip_high 4e-4 --test_folder sample658 --ratio 1.0
```

7. Inference for finetuned models

The following script runs inference on the test set of a finetuned model at checkpoint 1200.
```
python grpo.py --grpo_base_model qwen3_14b --use_gspo --drop_kl --reasoning_reward --equal_correctness --loss_type grpo --grpo_epsilon 3e-4 --clip_high 4e-4 --test_folder sample658 --ratio 1.0 --test --ckpt 1200 --n_run 1
```

## Inference on custom data without ground truth
You can also run the SLEDAI-2K scoring pipeline on your own clinical notes without ground truth labels (e.g. for simulated clinical implementation). This mode performs inference only (without evaluation). Please make sure the diagnostic criteria (for lab tests especially) align with your data.


[**Prompt Customizer Web Interface**](https://reneeleung.github.io/sledai-llm) – To help you align the guidelines and criteria with your local settings, we provide an interactive web interface. You can select between *Outpatient* (assess at visit date) and *Inpatient* (assess at admission date) note types, edit each descriptor's diagnostic criteria, exclusions, and lab thresholds, and customize the global prompt template. The tool automatically generates the corresponding prompts in real-time, which you can copy directly or download as `prompt.py` to replace the default version in `sledai-llm/prompts/`. This ensures the inference pipeline uses criteria that match your institution's lab methods, reference ranges, and clinical practices.

Place your clinical notes (.txt) in a folder under `data/`, e.g. `data/sample/`. Then run inference as follows:
```
python inference.py --model_name gptoss_120b --test_folder sample --n_run 1
```

Then to create a majority-vote scores CSV (under `results_inference/`):
```
python inference_summarise.py --model_name gptoss_120b --test_folder sample --n_runs 5
```

## License
This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.
