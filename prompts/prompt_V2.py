# for discharge notes; overrides prompt.py
guidelines_template = '''
You specialize in evaluating clinical notes for the Systemic lupus erythematosus (SLE) disease.
Given the descriptor {{ descriptor }}, score it as 0 or 1 based on the clinical note and information.
Please follow this guideline carefully:
1. Diagnostic criteria:
Given the information for {{ descriptor }}, assess the clinical note for evidence and evaluate whether the diagnostic criteria are met. Possible areas include:
- Diagnostic keywords: Check for the presence of diagnostic keywords which are strong indicators confirming criteria fulfilment. (In such cases, it is not necessary to verify each point within the criteria)
- Symptoms/signs keywords: Check for the presence of specific symptoms or signs
- Tests: Check for the value and unit of test results (check latest values; use default units if unspecified). And assess whether they meet criteria thresholds.
Relevancy check
- If no keywords are mentioned => `relevant = false`, `score = 0`, and skip remaining steps.
- If keywords are mentioned => `relevant = true`, and continue this guideline.
{{ intention_to_treat }}
Exclusions:
- Look for exclusions in the clinical note that may explain the symptom, but not SLE itself. These exclusions may justify scoring the descriptor but make the criteria `unfulfilled_diagnostic`.
- Only count exclusions if they are explicitly written in the note. If not mentioned, assume no exclusions.
- Drug exclusions only apply if the symptom is a common side effect, or if the doctor suspects the drug caused it.
If `relevant = true`, classify the diagnostic criteria as:
- 'fulfilled' (clear evidence the descriptor is met)
- 'unfulfilled_negated' (the absence of symptoms/diagnosis is explicitly stated in the clinical note)
- 'unfulfilled_diagnostic' (not enough evidence)
- 'uncertain' (doctor is uncertain or diagnostic ambiguity)
Notes and nuances:
- Terms such as "decrease/subsided/less/reduced/improved/similar/no increase in" still imply current symptom presence
- '?' or 'vs' indicates physician uncertainty, so criteria should be 'uncertain'
- Timepoint for Assessment: The reference point for calculating the SLEDAI-2K score is the time of hospital admission. If clinical parameters differ between the emergency department (ED) and admission, use the value documented at admission.
- Prioritization of findings: Admission documentation takes precedence over earlier ED or HPI mentions. If a descriptor is present in the ED but absent at admission, it should not be scored. Earlier mentions are only considered if no admission documentation exists. For example, a fever noted in the ED but resolved by admission should not contribute to the score.
- Handling duplicated laboratory tests: If duplicate laboratory tests are identified after admission, only the first result should be considered.
- If multiple reference ranges exist for the descriptor, check the report date and apply the reference range that corresponds to the time of testing
- Scan the entire clinical note for all mentions of descriptor keywords. Do not stop at the first mention.
- If keywords appear in multiple parts of the note, check whether they refer to the same time frame or episode. If yes, evaluate them together. If no, otherwise, evaluate each mention independently.
- If any independent mention fulfills the criteria, it can support final scoring of the descriptor.
{{ npsle_tips }}
Additional tips:
- Core lupus drug abbreviations include HCQ (hydroxychloroquine), P/PRED (prednisone), MMF/MPA (mycophenolate), AZA (azathioprine), BEL (belimumab), LEF(Leflunomide), RTX (rituximab), CTX/CYC (cyclophosphamide), TAC/FK506/FK (tacrolimus), and CsA/CYA (cyclosporine).
- 'P' followed by a number (e.g. P5, P7.5, P20) refers to prescribing and administering oral prednisone at the specified dose in milligrams (mg).
- The term 'flare' in clinical impressions acts as a diagnostic trigger: it confirms active manifestations fulfilling specific SLEDAI descriptors (e.g. cutaneous flare fulfills lupus rash).
- In medical documentation, X/52 denotes X weeks and X/12 denotes X months, reflecting durations based on yearly cycles (52 weeks or 12 months).(e.g., 2/52 = 2 weeks, 1/12 = 1 month).
- The value "trace" for test results means +/- (neither positive nor negative)

2. Time frame:
After identifying relevant keywords, symptoms, or test results in the diagnostic assessment, determine how recently the identified entity or finding occurred.
Time classification should reflect the current status of the symptom as of the documentation date, not when it first began. For example, if the note states 'onset 3 months ago' or '3 months already', it implies the symptom has been present continuously and is still active at the time of admission, so the time is still considered within_10days.
If the note explicitly states that the symptom has resolved, then the time should reflect when it was last active.
Discharge note rules:
- In the history of present illness section: if timing is not explicitly stated (e.g. "one week ago"), classify as time_uncertain.
- In the emergency department (ED) documentation: unless otherwise specified, classify findings as within_10days
- At hospital admission (or on the floor): findings are prioritized and should be classified as within_10days.

Assign one of the following categories with respect to the time of admission:
- 'within_10days' (descriptor is active within the last 10 days)
- '11_to_30days' (active more than 10 days ago but less than 30 days ago)
- '30days_ago' (entity was present 30 days ago)
- 'time_uncertain' (timing of entity cannot be determined)
Tips:
- Use context from the same part of the note where the descriptor was identified
- "recent/frequent/recurrent" => within_10days
- "occasional/sometimes/last visit/last time/on and off" => time_uncertain
- if only month and year provided: if match note date => 11_to_30days; otherwise => time_uncertain
Note that all dates mentioned should follow the format dd/mm/yyyy, unless it doesn't make sense.
For time_uncertain or 30days_ago, the descriptor score should be 0.

3. Score calculation:
Descriptor `score = 1` only if both:
(1) criteria must be 'fulfilled'
(2) time is either 'within_10days' or '11_to_30days'
Output the score in JSON format.
Include:
- "confidence_score": a number from 0 to 10 indicating how confident you are that your predicted score (0 or 1) accurately reflects whether the diagnostic criteria are met, based solely on the information available in the clinical note.
  - 10 = You are fully confident your prediction is correct, based on clear and direct evidence in the note. This includes explicit confirmation of the criteria (for score 1), explicit negations or absence of relevant keywords (for score 0).
  - 0 = You have no confidence in your prediction due to ambiguity, conflicting statements, vague language, or missing context in the note.
  - Scores between 1-9 reflect varying degrees of uncertainty, partial evidence, indirect phrasing, or incomplete documentation.
  - Note: Your confidence should reflect the clarity and completeness of the clinical note — not the doctor's intent, external medical knowledge, or pending test results. For example:
    - If the note says "? alopecia", you may be highly confident that the physician is uncertain, and therefore confident in assigning score 0.
    - If a test is mentioned but no result is provided, you may be confident that the criteria are not met, even if the test result is pending.
Your confidence should reflect how well the note supports your prediction — not whether the criteria are truly met in reality.
- "rationale": a 1-3 sentence explanation of the score. Mention relevant symptoms/signs, tests, any exclusions, time, etc. that helped you conclude this score. Use exact quoted text if citing clinical notes.


Diagnostic information for descriptor {{ descriptor }}:
{{ information }}

{{ keywords }}
'''

clinical_note_template = '''
==========================================================
Clinical Note:
{{ clinical_note }}

'''
score_template = guidelines_template + clinical_note_template

definitions = {
    'low_complement': '''Decrease in CH50, C3, or C4:
- Use lab flags first:
  - "low”, “reduced”, or similar terms => fulfilled
  - “nl” (normal), "high" => unfulfilled
  - trend-based terms like “lower” => uncertain
  - If a flag is present, it overrides the numeric value even if the value doesn't meet the threshold.
- If no flags or reference ranges are provided, use the hospital thresholds below:
Reference for complement in this study (no test for CH50 in our study): 
Item |	Reference (mg/dL)
C3	 |   <90
C4	 |   <10
''',


    'increased_DNA_binding': '''Increased DNA binding above laboratory reference range.
Qualitative values (such as "positive", "high", "+", "rising", or similar terms) should be considered uncertain for ELISA, but should be considered fulfilled for other methods.

NB:  If the methodology for increased DNA binding is not mentioned, we assume it is not ELISA.

Important:
- If the clinical note states a reference range (e.g. immunofluorescence), often in brackets, use its provided reference. 
- “nl” means normal range
''',

    'fever': '''Diagnostic criteria:
>38°C (Exclude infectious cause) 

Exclusions:
-	Infection (usually have high WBC, high CRP or definite localizing infective foci)
-	malignancy (especially lymphoma)

Important:
Temperature is often recorded during physical exam at admission. This value should take precendence over history of present illness.
''',

}

