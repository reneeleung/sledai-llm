import os
import pandas as pd
import sys

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, parent_dir)
from prompts.prompt import descriptors, sledai_weights

undercase = lambda s: s[:1].lower() + s[1:] if s[1].lower() == s[1] else s
uppercase = lambda s: s[0].upper() + s[1:]

descriptors = [uppercase(d) for d in descriptors]
descriptors_hard = [uppercase(d) for d, v in sledai_weights.items() if v >= 8]
event_types = ['Intention_to_treat', 'Exclusions', 'Treatment_response', 'Symptoms_Signs', 'Paraclinical_tests', 'Time', 'History']

map_criteria = lambda s: {
    'yes': 'fulfilled',
    'negation': 'unfulfilled_negated',
    'no': 'unfulfilled_diagnostic',
    'uncertain': 'uncertain', #'unfulfilled_diagnostic',
}[s]


def main():
    #data_dir = 'sample658/'
    #benchmark_name = 'sample658_entities_gold.csv'
    #benchmark_scores_name = 'sample658_scores_gold.csv'
    data_dir = 'sledai-notes/'
    benchmark_name = 'sledai-notes_entities_gold.csv'
    benchmark_scores_name = 'sledai-notes_scores_gold.csv'

    ann_files = [file for file in os.listdir(data_dir) if file.endswith('.ann')]
    annotations = []

    for file in ann_files:
        print(file)
        ann = {'filename': file.replace('.ann', '.txt')}
        labels = {}
        events = {}
        vals_units = {}   
        with open(data_dir+file) as f:
            lines = f.readlines()
        for line in lines:
            ents = line.strip().split('\t')
            if ents[0].startswith('T'):
                entity_type, start, _ = ents[1].split(maxsplit=2)
                if entity_type in descriptors:
                    labels[ents[0]] = {
                        'entity': entity_type,
                        'matched': ents[-1],
                        'start': int(start),
                    }
                elif entity_type == 'Value':
                    vals_units[ents[0]] = {'value': ents[-1]}
                elif entity_type == 'Unit':
                    vals_units[ents[0]] = {'unit': ents[-1]}
                elif entity_type in event_types:
                    events[ents[0]] = {'matched': ents[-1]}
                    if entity_type == 'Time':
                        events[ents[0]].update({'event': 'Time'})
                else:
                    print('Unrecognized annotation: ', line.strip())
            elif ents[0].startswith('E'):
                subents = ents[1].split(':')
                if subents[0] in ['Value', 'Unit']:
                    vals_units[ents[0]] = vals_units[subents[1]]
                elif subents[0] in event_types:
                    events[subents[1]].update({'event': subents[0]})
                    events[ents[0]] = events[subents[1]]
                else:
                    print('Unrecognized value for E: ', subents[0])
                    print(subents)

            elif ents[0].startswith('A'):
                attribute_type, tagged, attribute_value = ents[1].split()
                if attribute_type == 'time_nature':
                    if tagged in labels:
                        labels[tagged].update({'time': attribute_value,})
                    elif tagged in events:
                        events[tagged].update({'time': attribute_value,})
                elif attribute_type == 'SLEDAI_criteria':
                    if tagged in labels:
                        labels[tagged].update({'criteria': 'criteria_' + map_criteria(attribute_value),})
                elif attribute_type in ['special_entity']:
                    if tagged in labels:
                        labels[tagged].update({'special_entity_value': attribute_value,})
                elif attribute_type in ['nature_of_intention_to_treat']:
                    if tagged in labels:
                        labels[tagged].update({'nature_of_intention_to_treat': attribute_value,})
                else:
                    print('Unrecognized tag: ', attribute_type)
            elif ents[0].startswith('R'):
                relation_type, arg1, arg2 = ents[1].split()
                if relation_type == '_links_to_':
                    from_link = arg1.split(':')[1]
                    to_link = arg2.split(':')[1]
                    if from_link in vals_units:
                        labels[to_link].update({'value': vals_units[from_link],})
                    elif from_link in events:
                        event = events[from_link]
                        if event['event'] not in labels[to_link]:
                            labels[to_link][event['event']] = []
                        labels[to_link][event['event']].append(event['matched'],)
                    else:
                        print('Unable to find link source: ', to_link)
                elif relation_type == '_is_time_of_':
                    pass
                    # do nothing, because time is already tagged in entity
                elif relation_type == '_is_unit_of_':
                    from_link = arg1.split(':')[1]
                    to_link = arg2.split(':')[1]
                    vals_units[to_link].update(vals_units[from_link])
                else:
                    print('Unrecognized relation: ', relation_type)
        for event in events.values():
            if event['event'] == 'Time' and 'time' not in event:
                print('WARNING: missing Time attribute in Time event entity')
        for entity in descriptors:
            # check if descrip is in labels
            for v in labels.values():
                if v['entity'] == entity:
                    if entity not in ann:
                        ann[entity] = []
                    to_add = validate(v)
                    if to_add:
                        ann[entity].append(to_add)
            if entity in ann:
                ann[entity] = sorted(ann[entity], key=lambda x: x['start'])
        annotations.append(ann)

    df = pd.DataFrame(annotations)
    print('Missing entities: ', set(descriptors)-set(df.columns))
    df.rename(columns={col: undercase(col) for col in df.columns}, inplace=True)
    df.sort_values(by='filename', inplace=True)
    df.to_csv(benchmark_name, index=False)
    # reports without any annotations
    unannotated = df[df.iloc[:, 1:].isna().all(axis=1)].filename.tolist()
    print('Unannotated:', unannotated)

    df_scores = entities_to_scores(df)
    df_scores.to_csv(benchmark_scores_name, index=False)


def validate(obj):
    try:
        entity = obj['entity']
        assert entity in descriptors
        res_obj = {
            'matched': obj['matched'],
            'time': obj['time'],
            'start': obj['start'],
            'criteria': obj['criteria'],
        }
        if 'special_entity_value' in obj:
            res_obj.update({'special_entity_value': obj['special_entity_value'],})
        if entity in descriptors_hard and 'nature_of_intention_to_treat' not in obj:
            print('WARNING: Missing nature_of_intention_to_treat')
        if 'nature_of_intention_to_treat' in obj:
            res_obj.update({'nature_of_intention_to_treat': obj['nature_of_intention_to_treat'],})
        if 'value' in obj:
            res_obj.update({'value': obj['value'],})
        for event in event_types:
            if event in obj:
                res_obj.update({event: obj[event]})
    except:
        print(obj)
        print(f"WARNING: discarding value {obj['matched']} due to missing information!")
        return None
    return res_obj

def entities_to_scores(df):
    descrips = [undercase(d) for d in descriptors]
    descrips_hard = [undercase(d) for d in descriptors_hard]
    scores = {}
    files = df.filename.tolist()
    for f in files:
        scores[f] = {}
        for descrip in descrips:
            scores[f][descrip] = 0
            if descrip not in df.columns: # not annotated at all
                continue
            entities = df[df.filename == f][descrip].iloc[0]
            if type(entities) != list:
                continue
            for ent in entities:
                if ent['criteria'] == 'criteria_fulfilled' and ent['time'] not in ['30days_ago', 'time_uncertain']:
                    if descrip in descrips_hard and ('nature_of_intention_to_treat' not in ent or ent['nature_of_intention_to_treat'] != 'treat_escalated'):
                        continue
                    scores[f][descrip] = 1
    df_scores = pd.DataFrame(scores).transpose()
    df_scores.reset_index(inplace=True)
    df_scores.rename({'index': 'filename'}, axis=1, inplace=True)
    df_scores.sort_values(by='filename', inplace=True)
    df_scores['final_score'] = df_scores.apply(lambda row: sum(row[descrip] * sledai_weights[descrip] for descrip in descrips), axis=1)
    return df_scores


if __name__ == '__main__':
    main()
