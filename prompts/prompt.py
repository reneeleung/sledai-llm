## Run save_prompts.py whenever there are new changes to this file

TYPE_A = 'type_a'
TYPE_B = 'type_b'

weights = [
    ('seizure', 8, TYPE_A),
    ('psychosis', 8, TYPE_A),
    ('organic_brain_syndrome', 8, TYPE_A),
    ('visual_disturbance', 8, TYPE_A),
    ('cranial_nerve_disorder', 8, TYPE_A),
    ('lupus_headache', 8, TYPE_A),
    ('CVA', 8, TYPE_A),
    ('vasculitis', 8, TYPE_A),
    ('arthritis', 4, TYPE_A),
    ('myositis', 4, TYPE_A),
    ('urinary_casts', 4, TYPE_B),
    ('hematuria', 4, TYPE_B),
    ('proteinuria', 4, TYPE_B),
    ('pyuria', 4, TYPE_B),
    ('rash', 2, TYPE_A),
    ('alopecia', 2, TYPE_A),
    ('mucosal_ulcers', 2, TYPE_A),
    ('pleurisy', 2, TYPE_A),
    ('pericarditis', 2, TYPE_A),
    ('low_complement', 2, TYPE_B),
    ('increased_DNA_binding', 2, TYPE_B),
    ('fever', 1, TYPE_A),
    ('thrombocytopenia', 1, TYPE_B),
    ('leukopenia', 1, TYPE_B)
]

descriptors = [w[0] for w in weights]
sledai_weights = {w[0]: w[1] for w in weights}
type_a_hard = [w[0] for w in weights if w[1] >= 8]
type_a_others = [w[0] for w in weights if w[2] == TYPE_A and w[0] not in type_a_hard]
type_b = [w[0] for w in weights if w[2] == TYPE_B]

treatment_response_prompt = '''- Treatment response: For cases of {{ descriptor }} where documented positive symptoms/signs/tests do not not fully meet diagnostic thresholds, criteria could be fulfilled if either:
(a) a documented positive response to lupus-directed therapeutic trials (e.g. steroids, antimalarials, immunosuppressants, or biologics), or
(b) doctor's stated intention to initiate or escalate lupus-directed treatment.
Exception: Rash that improves with steroids alone is insufficient to establish lupus etiology.
'''

intention_to_treat_prompt = '''- Intention to treat: The doctor's treatment plans must include the initiation or escalation of steroids (e.g. prednisone, prednisolone, glucocorticoids), immunosuppressants (e.g. mycophenolate mofetil, cyclophosphamide, azathioprine, cyclosporine, tacrolimus), or biologics (e.g. belimumab, rituximab).
Classify the nature_of_intention_to_treat:
- 'treat_escalated' (lupus-specific treatment is initiated or escalated)
- 'treat_de_escalate' (treatment is reduced, tapered, or discontinued)
- 'wait_and_see' (no treatment change is made; intent is to monitor and reassess)
Important: If diagnostic keywords are mentioned or the diagnostic criteria are met, but `nature_of_intention_to_treat` is not treat_escalated, then the criteria should be considered unfulfilled_diagnostic (see below).
'''

nature_of_intention_to_treat_prompt = ''''nature_of_intention_to_treat': 'treat_escalated' | 'wait_and_see' | 'treat_de_escalate' | null, // write null only if 'relevant' field is false
    '''

npsle_tips = '''- Terms such as "NPSLE," "CNS lupus," and "lupus cerebritis" are non-specific and can correspond to several distinct neuropsychiatric items in the SLEDAI-2K (e.g., Seizures, Psychosis, Organic Brain Syndrome, CVA). Therefore, when these keywords are present, the first step is to determine if a specific type of NPSLE was documented by the physician to assign the correct SLEDAI-2K item. When the clinical notes are ambiguous, a careful review is essential to differentiate between overlapping manifestations, such as psychosis versus organic brain syndrome, or cranial nerve disorder versus stroke.
'''

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
- If multiple values are present for the same test, use the most recent. Watch for collection dates or historical references (terms like 'last'/'prev'). For results 'pending', it is uncertain.
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
Time classification should reflect the current status of the symptom as of the documentation date, not when it first began. For example, if the note states 'onset 3 months ago' or '3 months already', it implies the symptom has been present continuously and is still active currently, so the time is still considered within_10days.
If the note explicitly states that the symptom has resolved, then the time should reflect when it was last active.
Assign one of the following categories from the date of the clinical note:
- 'within_10days' (descriptor is active within the last 10 days)
- '11_to_30days' (active more than 10 days ago but less than 30 days ago)
- '30days_ago' (entity was present 30 days ago)
- 'time_uncertain' (timing of entity cannot be determined)
Tips:
- Use context from the same part of the note where the descriptor was identified
- "recent/frequent/recurrent" => within_10days
- "occasional/sometimes/last visit/last time/on and off" => time_uncertain
- if only month and year provided: if match note date => 11_to_30days; otherwise => time_uncertain
- if no date is specified => default to within_10days unless indications suggest otherwise
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
The clinical note is dated {{ date }} (dd/mm/yyyy).

Clinical Note:
{{ clinical_note }}

'''
score_template = guidelines_template + clinical_note_template

output_template = '''===================================================
Output JSON format:
```
{
    'descriptor': '{{ descriptor }}', // required
    'relevant': true or false, // required; write true if keywords are mentioned in the clinical note
    'criteria': 'unfulfilled_negated' | 'unfulfilled_diagnostic' | 'fulfilled' | 'uncertain' | null, // write null if 'relevant' field is false
    {{ nature_of_intention_to_treat }}'time': 'within_10days' | '11_to_30days' | '30days_ago' | 'time_uncertain' | null, // write null if 'relevant' field is false
    'score': 0 or 1, // required
    'confidence_score': 0 to 10, // required
    'rationale': '' // required
}
```
'''

keywords_list = {
    ## TYPE A
    'seizure': {
        'diagnostic': 'NPSLE, seizure, epilepsy, grand mal, petit mal, drop attack',
        'symptoms': 'loss of consciousness (LOC), loss of awareness, tonic, clonic, myoclonic, atonic, generalized stiffness, twitching, uprolling eyeballs, tongue bite',
    },
    'psychosis': {
        'diagnostic': 'psychosis, psychotic disorder',
        'symptoms': 'psychotic, delusions, hallucinations, disorganized thinking/speech, grossly disorganized or abnormal motor behavior, catatonic behavior, paranoia, psychotic beliefs, false beliefs, bizarre beliefs, weird beliefs, sensory misperceptions, perceptual disturbances, illusions, phantom sensations',
    },
    'organic_brain_syndrome': {
        'diagnostic': 'NPSLE, organic brain syndrome, organic brain disorder, acute confusional state, delirium, encephalopathy, neurocognitive disorders',
        'symptoms': 'disturbance of consciousness, impaired attention, reduced attention, attention deficit, shift attention, reduced sustain, impaired sustain, reduced ability to direct, reduced ability to focus, reduced ability to sustain, impaired awareness, decreased awareness, reduced awareness, impaired orientation, disorientation, impaired cognition, cognitive impairment, decreased cognitive, impaired cognitive, memory deficit, memory impairment, memory loss, impaired recall, hypomnesia, amnesia, incoherent speech, impaired language ability, disorder language, impaired perception, misinterpretations, illusions, hallucinations, impaired mental function, hyper-aroused/hyperactive, hypo-aroused/hypoactive, coma, sleepiness, insomnia, difficulty falling asleep, nighttime agitation, lack of responsiveness, drowsiness',
    },
    'visual_disturbance': {
        'diagnostic': 'retinal disease(s), retinopathy, choroidopathy, optic neuritis, retrobulbar neuritis',
        'symptoms': 'loss of vision, blurring of vision, visual impairment, orbital pain, eye pain, relative afferent pupillary deficit (RAPD), choroid hemorrhage, retinal hemorrhages, cotton-wool spots, exudates, cytoid bodies',
    },
    'cranial_nerve_disorder': {
        'diagnostic': 'NPSLE, Bell\'s palsy, cranial mononeuropathy, cranial polyneuropathy, cranial neuritis, PALSY, paralysis, neuropathy, neuritis, or discorder with the following nerves: cranial nerve, olfactory nerve, optic nerve, oculomotor nerve, trochlear nerve, abducens nerve, trigenminal nerve, facial nerve, vestibulo-cochlear nerve, glossopharyngeal nerve, vagus nerve, accessory nerve, hypoglossal nerve, CN I, CN II, CN III, CN IV, CN V, CN VI, CN VII, CN VIII, CN IX, CN X, CN XI, CN XII, 1st nerve, 2nd nerve, 3rd nerve, 4th nerve, 5th nerve, 6th nerve, 7th nerve, 8th nerve, 9th nerve, 10th nerve, 11th nerve, 12th nerve',
        'symptoms': 'nerve paralysis, nerve PALSY, nerve neuropathy',
    },
    'lupus_headache': {
        'diagnostic': 'lupus headache',
        'symptoms': 'headache, cephalagias, migraine',
    },
    'CVA': {
        'diagnostic': 'stroke, subarachnoid, hemorrhage, cerebral venous, thrombosis, TIA, transient ischaemic attack, sinus thrombosis',
        'symptoms': 'hemiplegia, unilateral weakness',
    },
    'vasculitis': {
        'diagnostic': 'cutaneous vasculitis, vasculitic rash, vasculitic (must be skin-related)',
        'symptoms': 'skin ulceration, skin ulcer(s), gangrene, necorsis, lender finger nodules, periungual infarction, splinter hemorrhages',
    },
    'arthritis': {
        'diagnostic': 'arthritis, pauciarticular, polyarthritis, polyarticular',
        'symptoms': 'arthralgia, tenderness, swelling, effusion, morning stiffness, joint pain, pain in these locations: MCP, DIP, PIP, knee, hip, wrist',
        'paraclinical': 'synovial fluid, synovitis, synovial inflammation, synovial proliferation',
    },
    'myositis': {
        'diagnostic': 'myositis',
        'symptoms': 'myalgia, muscle aching, muscle weakness',
        'paraclinical': 'elevated CK, CK+, ↑CK',
    },
    'rash': {
        'diagnostic': 'cutaneous flare, cutaneous lupus, CLE, lupus erythematosus (LE), malar rash, bullous lupus, toxic epidermal necrolysis variant (TEN), maculopapular lupus rash, photosensitive, discoid, DLE, hypertrophic (verrucous) lupus, lupus panniculitis (profundus), mucosal lupus, lupus erythematosus tumidus, chillblains, lichen planus overlap',
        'symptoms': 'rash',
    },
    'alopecia': {
        'diagnostic': 'hair loss, alopecia, aloperic',
    },
    'mucosal_ulcers': {
        'diagnostic': 'aphthous ulcer, ulceration, ulcers; the position of the ulcers should be the following: oral, mouth, mucosal, nasal, nasopharyngeal, palate, buccal, tongue',
    },
    'pleurisy': {
        'diagnostic': 'serositis, pleurisy, pleuritis',
        'symptoms': 'pleuritic chest pain, pleuritic pain, pleural rub, pleural thickening',
        'paraclinical': 'pleural effusion, pleural fluid',
    },
    'pericarditis': {
        'diagnostic': 'pericarditis, hydropericardium',
        'symptoms': 'pericardial pain, pericardial chest pain, pericardial rub, cardiac tamponade',
        'paraclinical': 'pericardial effusion, pericardial fluid',
    },
    'fever': {
        'symptoms': 'PUO, fever, any records of temperature more than 38, e.g. Temp ?, ? ℃, ? C',
    },
    ## TYPE B
    'urinary_casts': {
        'keywords': 'heme-granular casts, RBC casts',
    },
    'hematuria': {
        'keywords': 'hematuria, urine RBC, URBC, urine RC',
    },
    'proteinuria': {
        'keywords': 'UP, urine protein, urine P, upr, KSP, UPC, UP/C, UPCR, P/Cr, PC ratio, P/C, 24hr urine protein, 24hr urine pr, 24hr urine x p, 24hUP',
    },
    'pyuria': {
        'keywords': 'pyuria, urine WBC, UWBC, urine WC',
    },
    'low_complement': {
        'keywords': 'C3, C4, C3/4, complements'
    },
    'increased_DNA_binding': {
        'keywords': 'anti-ds DNA, anti DNA, dsDNA'
    },
    'thrombocytopenia': {
        'keywords': 'PLT, platelet',
    },
    'leukopenia': {
        'keywords': 'WCC, WBC',
    },
}

definitions = {
    'proteinuria': '''Either one: 
A.	24-hour urine : >0.50 gram/24 hours.
B.	Urine protein/creatinine > 0.50 mg/mg. (This is equivalent to 0.50 g/g or 50 mg/mmol. Do not convert further - these units are already standardized and interchangeable.)

NB: UP dipstick results (e.g., "+", "+++", "+ve") are generally uncertain. Numeric values must meet criteria above.
Exception: A dipstick reading of 3+ or greater may be scored as fulfilled when correlated with a physician's clinical impression of a lupus flare (i.e., one necessitating escalation of therapy for lupus nephritis).

If the two results are conflicting at the same time, the 24-hour protein result shall prevail.
If UPC unit is unspecified, presume mg/mmol scale for values >20, mg/mg for values <5, and flag uncertain for values in between.
''',

    'pyuria': '''>5 white blood cells/high-power field and abnormal urine protein (dipstick positive (UP+ or above) or Urine protein/creatinine > 0.15mg/mg (15mg/mmol or 0.15g/g) or 24-hour urine protein >0.15gram/24 hours).
In cases where multiple urine protein assessments are available and the results conflict, please prioritize according to the following hierarchy:
24-hour urine protein > urine protein/creatinine (UPC) > dipstick
Exclude infection. Possible urine infection types include E.coli, Enterococcus, Klebsiella, Pseudomonas, AFB/tuberculosis.
NB: in our study, urine WBC 2+, urine WBC ++, etc.,, or urine WBC >= 10-50/uL can be considered as >5 white blood cells/high-power field.
Important: "urine WBC +" should not be counted.
Note: if the doctor decides to treat patient with antibiotics or conduct further tests to identify the specific pathogen causing the symptoms, the presence of pyuria is likely due to an infection.''',

    'rash': '''Diagnostic criteria:
Either one form of lupus rash from these three class of lupus erythematosus:
A. Acute cutaneous lupus erythematosus (ACLE), either one:
  1. lupus malar rash;
  2. bullous lupus; 
  3. toxic epidermal necrolysis variant of SLE; 
  4. maculopapular lupus rash; 
  5. photosensitive lupus rash in the absence of dermatomyositis; 
B. subacute cutaneous lupus erythematosus (SCLE), either one:
  1. Annular form
  2. Papulosquamous form
C. Chronic cutaneous lupus erythematosus (CCLE), either one:
  1. classical discoid lupus erythematosus (DLE)
  2. localized DLE (above the neck)
  3. generalized DLE (above and below the neck)
  4. hypertrophic (verrucous) lupus
  5. lupus panniculitis (profundus)
  6. mucosal lupus
  7. lupus erythematosus tumidus
  8. chillblains lupus (CHLE, pernio)
  9. lichen planus overlap 

Note: A "lupus rash" can only be scored if it was clinically diagnosed as such. Descriptions of skin changes based solely on morphology and location are considered insufficient for scoring a “lupus rash”, unless the rash was documented as a classic manifestation (e.g., typical malar distribution). Furthermore, rashes described solely as "skin damage" or residual changes should not be scored, as the SLEDAI-2K is designed to capture active inflammatory rash.
Here is the vocabulary to help distinguish between lupus activity versus damage:
Activity (erythema):
pink, faint erythema, pinkish, faint erythema,
faintly erythematous, mild erythema, mildly erythematous, mild redness, mildly red,
erythematous, erythema, moderate erythema, moderately erythematous. moderate erythematous,
red, redness, reddish, dark red, deep red, deeply red, deep reddish, deeply reddish, purple, purplish, violaceous

Activity (scale/hypertrophy):
Scale, scaling, scaly, follicular plugging, follicular prominence, carpet tacking, carpet tack sign, perifollicular scale 
Hypertrophy, hypertrophic, hyperkeratosis, hyperkeratotic

Damage (Dyspigmentation):
Hypopigmentation, hypopigmented, hyperpigmentation, hyperpigmented,
dyspigmentation, dyspigmented, pigmentary changes, brown, depigment, white

Damage (scarring/atrophy/panniculitis):
Scarring, scar, Atrophic scarring, atrophic, panniculitis, lipoatrophy, atrophic scar

-	Exclusions for ACLE: 
• Localized form: rosacea, seborrheic eczema, perioral dermatitis, tinea faciei, erysipelas
• Generalized form: dermatomyositis, viral and drug-induced rash, erythema multiforme, TEN
• Bullous lupus erythematosus (BLE): Epidermolysis bullosa acquisita, dermatitis herpetiformis (Duhring's disease), bullous pemphigoid, linear IgA-dermatosis, drug-induced bullous disorder, porphyria cutanea tarda

-	Exclusions for SCLE:
• Psoriasis vulgaris, tinea corporis, mycosis fungoides, erythema annulare centrifugum, dermatomyositis, pityriasis rubra pilaris, nummular eczema, drug-induced rash, seborrheic eczema, erythema multiforme /TEN, erythema gyratum repens

-	Exclusions for Discoid lupus erythematosus (DLE).:
• Actinic keratosis, tinea faciei, sarcoidosis, lupus vulgaris

-	Exclusions for Lupus erythematodes profundus (LEP):
• Various forms of panniculitis, malignant lymphoma (especially subcutaneous panniculitic T-cell lymphoma), subcutaneous sarcoidosis, panarteritis nodosa, morphea profunda, subcutaneous granuloma annulare

-	Exclusions for Chilblain lupus erythematosus (CHLE):
• Pernio (chilblains), lupus pernio (chronic form of skin sarcoidosis of the acral regions), acral vasculitis/vasculopathy

-	Exclusions for Lupus erythematosus tumidus (LET):
• Lymphocytic infiltration Jessner-Kanof or erythema arciforme et palpabile (see text), polymorphic light eruption, pseudolymphoma, B-cell lymphoma, plaque-like cutaneous mucinosis, solar urticaria
''',


    'alopecia': '''Diagnostic criteria:
Hair loss or alopecia

Exclusions:
-	alopecia areata
-	iron deficiency
-	androgenic alopecia
-	scarring alopecia
-   drug-induced alopecia
''',

    'mucosal_ulcers': '''Diagnostic criteria:

Oral or nasal (nasopharyngeal) ulceration observed by a clinician, including palate, buccal, tongue or nasal ulcers 

Exclusions:
-	Vasculitis
-	Behcet's
-	infection (herpes)
-	inflammatory bowel disease
-	reactive
''',


    'pleurisy': '''Diagnostic criteria:
Both  A and B:
A.	Pleuritic chest pain (typically sharp, worse with inspiration, improved by shallow breathing)
B.	pleural rub OR pleural thickening OR imaging confirmed pleuritic effusion (such as ultrasound, x-ray, CT scan, MRI)
Exclusions:
-	infection
-   uremia (BUN > 40 mg/dL)
''',


    'CVA': '''Diagnostic criteria:
One of the following and supporting radio imaging study, exclused arteriosclerosis:
A. Stroke syndrome: acute focal neurologic deficit persisting more than 24 hours (or lasting less than 24 hours with CT or MRI abnormality consistent with physical findings/symptoms
B. Transient ischemic attack: acute, focal neurologic deficit with clinical resolution within 24 hours (without corresponding lesion on CT or MRI)
C. Subarachnoid and intracranial hemorrhage: bleeding documented by CSF findings or MRI/CT
D. Sinus thrombosis: Acute, focal neurologic deficit in the presence of increased intracranial pressure
NB: The finding of unidentified bright objects on MRI without clinical manifestations is not classified at the present time. 

Exclusions: 
-	Aseptic meningitis (including drug-induced)
-	Drug-induced pseudotumor cerebri (oral contraceptives, sulfonamides, trimethoprim,  etc.)
-	CNS infection
-	Tumors and other structural lesions
-	Low intracranial pressure
-	Trauma
-	Metabolic headache that remits with elimination of cause (carbon monoxide exposure)
-	Withdrawal (caffeine, etc.)
-	Seizure/postictal state
-	Sepsis
-	Intracranial hemorrhage or vascular occlusion
''',


    'vasculitis': '''Diagnostic criteria:
Either one:
A.	clinician observed cutaneous vasculitis with at least one of the following description of lesions: Ulceration, gangrene, lender finger nodules, periungual infarction (or necrosis), splinter hemorrhages
B.	biopsy or angiogram proof of cutaneous vasculitis

Exclusions:
-mimics of vasculitis (Atheroembolic disease, Atheromatous vascular disease, Anti-phospholipid syndrome, Multiple myeloma, Infective endocarditis, Para-neoplastic syndromes, Genetic vascular disorders (e.g. Marfan’s syndrome), Autoinflammatory syndromes, Hypersensitivity reactions, Cocaine and amphetamine abuse)
-Infections (Tuberculosis, Hepatitis B, Hepatitis C, HIV)
-Malignancy (Lymphoma, Solid organ malignancy)
-Drugs (Penicillamine, Propylthiouracil, Hydralazine, Minocycline, Cocaine)
-Environmental exposure (including Dusts and Silica)
''',


    'arthritis': '''Diagnostic criteria:
Either one: 
A. two or more joints with pain and signs of inflammation (e.g., tenderness, swelling, or effusion) 
B. synovitis involving two or more joints characterized by swelling or effusion
C. two or more joints tenderness and 30 minutes or more of morning stiffness 

Exclusions: 
-	infection (a septic joint or as osteomyelitis): tuberculosis, Bacterial, viral 
-	stress fractures
-	Crystal arthritis: Gout, calcium pyrophosphate deposition disease
-   Noninflammatory arthritis, such as osteoarthritis and avascular necrosis (AVN)  (especially for hip, knee or shoulder)
-	Rheumatoid arthritis
''',


    'myositis': '''Diagnostic criteria:
All of the following: 
A. proximal muscle aching(myalgias)/weakness, 
B. associated with elevated creatine phosphokinase/aldolase or electromyogram (EMG) changes or a biopsy showing myositis 

Exclusions: 
-	CK elevation was unexplained, isolated, felt to be related to rhabdomyolysis, exertion, infection, or the toxic effect of medication (i.e., statin,hydroxychloroquine-induced myotoxicity)
-	cancer-associated myositis
-	metabolic muscle disease
''',


    'urinary_casts': '''Heme-granular or red blood cell casts.''',


    'hematuria': '''Diagnostic criteria:
All of the following:
A. >5 red blood cells/high-power field. Acceptable equivalents include:
- Urine RBC >= 2+ (e.g., 2+, ++, 2+ve, ++ve, +++ve, etc.)
- Urine RBC >30-58/uL
Important: "urine RBC +" should not be fulfilled.
Important: Values such as "high/moderate" or similar terms should be considered as uncertain. 
Note: Microscopic haematuria is most commonly defined as >3 red blood cells per high-power field on urinary microscopy, but this study uses a threshold of >5. Therefore, it should be considered uncertain.
Exclusions: stones, infection or other cause (menstruation).

B. abnormal urine protein:
- UP dipstick positive, or
- Urine protein/creatinine > 0.15mg/mg (equivalent to 15mg/mmol or 0.15g/g), or
- 24-hour urine protein > 0.15gram/24 hours).
In cases where multiple urine protein assessments are available and the results conflict, please prioritize according to the following hierarchy:
24-hour urine protein > urine protein/creatinine (UPC) > dipstick
''',


    'seizure': '''Diagnostic criteria:
A with or without the presence of B: 
A.	Independent description of seizure by a reliable witness
B.	EEG abnormalities

Exclusions:
-	Medications: quinolones, imipenem
-	Alcohol and drug withdrawal (phenothiazines, antipsychotics)
-	electrolyte imbalance (acidosis, serum sodium, calcium, and hypoglycemia)
-	organ failure (hepatic and renal failure)
-	infection
-	due to past irreversible CNS damage
-	Vasovagal syncope
-	Cardiac syncope
-	Hysteria
-	Hyperventilation
-	Tics
-	Narcolepsy and cataplexy
-	Labyrinthitis
-	Subarachnoid hemorrhage
-	Trauma
-	Panic attacks, conversion disorders, and malingering
-	hypersensitivity encephalopathy
''',


    'psychosis': '''Diagnostic criteria:
All of the following:
A.	At least one of the following:
  1. Delusions
  2. Hallucinations without insight (visual, olfactory, gustatory, tactile, or auditory)
  3. Disorganized thinking (speech) (frequent derailment; loose associations; incoherence; “word salad”)
  4. Grossly disorganized or abnormal motor behavior (childlike “silliness”; unpredictable agitation; catatonic behavior; negativism; mutism and stupor; catatonic excitement; stereotyped movements, staring; grimacing, mutism; echoing of speech)
  5. Negative symptoms (diminished emotional expression; avolition; alogia; anhedonia; asociality)

B.	The disturbance causes clinical distress or impairment in social, occupational, or other relevant areas of functioning.
C.	The disturbance does not occur exclusively during the course of a delirium.
D.	The disturbance is not better accounted for by another mental disorder (e.g., mania). 
Exclusions:
-	Uremia (BUN > 40 mg/dL)
-	Substance- or drug-induced psychotic disorder (including NSAIDs, antimalarials)
-	acidosis, or electrolyte imbalance
-	delirium
-	Primary psychotic disorder unrelated to SLE (e.g., schizophrenia)
-	Psychologically mediated reaction to SLE (brief reactive psychosis with major stressor)
''',


    'organic_brain_syndrome': '''Diagnostic Synonymous: 
organic brain syndrome
organic brain disorder
acute confusional state
delirium
encephalopathy
neurocognitive disorders

Diagnostic criteria:
All of the following:
A. A disturbance in attention (i.e., reduced ability to direct, focus, sustain, and shift attention) or awareness (reduced orientation to the environment)
B. Rapid onset and fluctuating clinical features: develops over a short period of time (usually hours to a few days), represents a change from baseline attention and awareness, and tends to fluctuate in severity during the course of a day
C. Plus at least two of the following:
  1. perceptual disturbance (misinterpretations, illusions, or hallucinations)
  2. incoherent speech
  3. insomnia or daytime drowsiness
  4. increased or decreased psychomotor activity (Hyperactive/ Hypoactive)

Exclusions:
-	Primary mental/neurologic disorder not related to SLE.
-	Metabolic disturbances (glucose > 25; serum sodium <125 or >155; serum calcium >3)

NB: Preexisting cognitive deficits are not an exclusion. If acute confusional state is superimposed on preexisting cognitive deficits, diagnose both.
''',


    'visual_disturbance': '''Diagnostic criteria:
Either (1) or (2)
(1) Retinopathy or choroidopathy with one criteria below, usually bilateral: 
A.	cytoid bodies (cotton-wool spots or retinal soft exudates)
B.	retinal hemorrhages
C.	serous exudate in the choroid
D.	serous hemorrhages in the choroid

(2) Optic neuritis
Clinical criteria (A), (B), or (C) if seen acutely; or at least one Paraclinical criteria with a medical history suggestive of optic neuritis
1. Clinical criteria:
A.	Monocular, subacute loss of vision associated with orbital pain worsening oneye movements, reduced contrast and colour vision, and relative afferent pupillary deficit (RAPD)
B.	Painless with all other features of (A).
C.	Binocular loss of vision with all features of (A) or (B).
2. Paraclinical criteria: 
A.	OCT: Corresponding optic disc swelling acutely or an inter-eye difference in the mGCIPL of >4% or >4 μm or in the pRNFL of >5% or >5 μm within 3 months after onset.
B.	MRI: Contrast enhancement of the symptomatic optic nerve and sheaths acutely or an intrinsic signal (looking brighter) increase within 3 months.

Exclusions: 
-	hypertension (BP > 180/120)
-	Infectious, post-infectious or post-vaccination
-	drug caused
-	drusen (for cytoid bodies)
-	Autoimmune ON: multiple sclerosis (MS), Aquaporin4 IgG antibodies-associated neuromyelitis optica spectrum disorder (NMOSD) or Anti-myelin oligodendrocytes glycoprotein antibody-associated disease (MOGAD)
''',


    'cranial_nerve_disorder': '''Diagnostic criteria:
New onset of focal sensory or motor neuropathy involving cranial nerves.
Syndrome corresponding to specific nerve function:
I.	Olfactory nerve: Loss of sense of smell, distortion of smell, and loss of olfactory discrimination 
II.	Optic nerve: [Intentionally omitted. Not evaluated under cranial nerve disorder criteria.]
III.	Oculomotor nerve: Ptosis of the upper eyelid and inability to rotate eye upward, downward, or inward (complete lesion), and/or dilated nonreactive pupil and paralysis of accommodation (interruption of parasympathetic fibers only)
IV.	Trochlear nerve: Extortion and weakness of downward movement of affected eye
V.	Abducens nerve: Weakness of eye abduction
VI.	Trigeminal nerve: Paroxysm of pain in lips, gums, cheek, or chin initiated by stimuli in trigger zone (trigeminal neuralgia) and sensory loss of the face or weakness of jaw muscles
VII.	Facial nerve: Unilateral or bilateral paralysis or facial expression muscles, impairment of taste, and hyperacusis (painful sensitivity to sounds)
VIII.	Vestibulo-cochlear nerve: Deafness, tinnitus (cochlear), dizziness and/or vertigo (vestibular)
IX.	Glossopharyngeal nerve: Swallowing difficulty, deviation of soft palate to normal side, anesthesia of posterior pharynx and/or glossopharyngeal neuralgia (unilateral stabbing pain in root of tongue and throat, triggered by coughing, sneezing, swallowing, and pressure on ear tragus)
X.	Vagus nerve: Soft palate droop, loss of the gag reflex, hoarseness, nasal voice, and/or loss of sensation at external auditory meatus.
XI.	Accessory nerve: Weakness and atrophy of sternocleidomastoid muscle and upper part of trapezius muscle.
XII.	Hypoglossal nerve: Paralysis of one side of tongue with deviation to the affected side

Exclusions: 
-	Nerve palsy caused by stroke, seizure, or intracranial hypertension
-	Skull fracture
-	Tumor: meningioma, carcinomatous meningitis, aneurysm
-	Infection: herpes zoster, neuroborreliosis, syphilis, mucormycosis
-	Miller Fisher syndrome
''',


    'lupus_headache': '''Diagnostic criteria:
Either type of headache below, and should be severe (disabling headache), persistent (lasts ≥3 days) also nonresponsive to narcotic analgesia (e.g. heroin, fentanyl, byprenorpine, oxycodone methadone, and morphine). 
A. Migraine
 
Migraine without aura: Idiopathic, recurrent headache manifested by attacks lasting 4-72 hours. Typical characteristics are unilateral location, pulsating quality, moderate to severe intensity, aggravation by routine physical activity, and associated with nausea, vomiting, photo- and phonophobia. At least 5 attacks fulfilling the above criteria.
Migraine with aura: Idiopathic, recurrent disorder manifested by attacks of neurologic symptoms localizable to cerebral cortex or brain stem, usually gradually developing over 5-20 minutes and lasting less than 60 minutes. Headache, nausea, and/or photophobia usually follow neurologic aura symptoms directly or after an interval of less than 1 hour. Headache usually lasts 4-72 hours, but may be completely absent.
B. Tension headache (episodic tension type headache)

Recurrent episodes of headaches lasting minutes to days. Pain typically pressing/tightening in quality, of mild to moderate intensity, bilateral in location, and does not worsen with routine physical activity. Nausea is rare, but photophobia and phonophobia may be present. At least 10 previous headaches fulfilling these criteria.
C. Cluster headache
 
Attacks of severe, strictly unilateral pain, orbital, supraorbital, and/or temporal, usually lasting 15-180 minutes and occurring from at least once every other day up to 8 times per day. Associated with one   or more of the following: conjunctival injection, lacrimation, nasal congestion, rhinorrhea, forehead and facial sweating, myosis, ptosis, eyelid edema. Attacks occur in series for weeks or months ("cluster" periods) separated by remissions of usually months or years.
D. Headache from intracranial hypertension (Pseudotumor cerebri, benign intracranial hypertension)

All of the following:
Increased intracranial pressure (200 mm HiO) measured by lumbar puncture
Normal neurologic findings except for papilledema and possible nerve VI palsy
No mass lesion and no ventricular enlargement on neuroimaging
Normal or low protein and normal white cell count in CSF
No evidence of venous sinus thrombosis
E. Intractable headache, nonspecific

Exclusions: 
-	Aseptic meningitis (including drug-induced)
-	Drug-induced pseudotumor cerebri (oral contraceptives, sulfonamides, trimethoprim,  etc.)
-	CNS infection (meningitis/encephalitis)
-	Tumors and other structural lesions
-	Low intracranial pressure
-	Trauma
-	Metabolic headache that remits with elimination of cause (carbon monoxide exposure)
-	Withdrawal (caffeine, etc.)
-	Seizure/postictal state
-	Sepsis
-	Intracranial hemorrhage or vascular occlusion
''',


    'pericarditis': '''Diagnostic criteria:
Both  A and B:
A.	pericardial pain (typically sharp, worse with inspiration, improved by leaning forward)
B.	pericardial rub OR EKG with new widespread ST-elevation or PR depression OR new/worsen imaging confirmed pericardial effusion (such as ultrasound, x-ray, CT scan, MRI)

Exclusions:
-	infection (coxsackievirus, mycoplasma, tuberculosis)
-	uremia (BUN > 40 mg/dL)
-	Dressler's pericarditis (post-myocardial infarction syndrome)
''',


    'low_complement': '''Decrease in CH50, C3, or C4:
- Use lab flags first:
  - "low”, “reduced”, or similar terms => fulfilled
  - “nl” (normal), "high" => unfulfilled
  - trend-based terms like “lower” => uncertain
  - If a flag is present, it overrides the numeric value even if the value doesn't meet the threshold.
- If no flags or reference ranges are provided, use the hospital thresholds below:
Reference for complement in this study (no test for CH50 in our study): 
Time period         | item  |	Reference (mg/dL)
24/12/2018 till now |	C3	|   <90
before 24/12/2018   |	C3	|   <76
24/12/2018 till now |	C4	|   <10
before 24/12/2018   |	C4	|   <9
For C3: Presume mg/dL scale for values >10, g/L for values <2, and flag uncertain for values in between.
''',


    'increased_DNA_binding': '''Increased DNA binding above laboratory reference range, except ELISA: twice above laboratory reference range.

NB: If the methodology for increased DNA binding is not mentioned, we assume it is ELISA.
Qualitative values (such as "high", "+", "rising", or similar terms) should be considered uncertain for ELISA, but should be considered fulfilled for other methods.

The cut-off for the ELISA method should be based on reference range provided by clinical notes when available; otherwise, our QMH's reference range for ELISA should be applied:
Time period             |	Reference
1/2/2021 till now       |	>10 IU/ml
21/1/2013 to 1/2/2021   |	>25 IU/ml
before 21/1/2013	    |   >67.5 IU/ml
Important:
- If the clinical note states a reference range (e.g. immunofluorescence), often in brackets, use its provided reference. 
- “nl” means normal range
''',


    'fever': '''Diagnostic criteria:
>38°C (Exclude infectious cause) 

Exclusions:
-	Infection (usually have high WBC, high CRP or definite localizing infective foci)
-	malignancy (especially lymphoma)
''',


    'thrombocytopenia': '''Thrombocytopenia (platelets <100,000/mm3 or <100 x 10^9/L), in the absence of other known causes such as drugs, portal hypertension, and thrombotic thrombocytopenic purpura.
Important: Qualitative values such as "low", "mild", or similar terms should be considered as uncertain. The exact numerical value must be stated and meet the criteria above.
In clinical practice, the default unit is 1000/mm3 or 10^9/L''',


    'leukopenia': '''Leucocyte count, < 3,000/mm3 or  < 3 x 10^9/L white blood cells. Exclude Felty's, drug causes and portal hypertension.
Important: Qualitative values such as "low" or similar terms should be considered as uncertain. The exact numerical value must be stated and meet the criteria above.
Also, only consider leucocyte counts labeled as WCC or WBC. Do not consider ANC.
In clinical practice, the default unit is 1000/mm3 or 10^9/L''',
}

