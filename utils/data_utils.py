def visualise_relevancy(ax, counts):
    labels = ['Unannotated', 'Annotated']
    ax.bar(labels, counts)
    ax.set_title('Relevancy Distribution')
    for i in range(len(counts)):
        ax.text(i, counts[i] + 0.1, str(counts[i]), ha='center')

def visualise_criteria(ax, criterias):
    labels = {'fulfilled': 0, 'unfulfilled_negated': 0, 'unfulfilled_diagnostic': 0, 'uncertain': 0}
    for c in criterias:
        labels[c] += 1
    counts = list(labels.values())
    ax.bar(labels.keys(), counts)
    ax.set_title('Criteria Distribution')
    for i in range(len(counts)):
        ax.text(i, counts[i] + 0.1, str(counts[i]), ha='center')
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45)

def visualise_time(ax, times):
    labels = {'within_10days': 0, '11_to_30days': 0, '30days_ago': 0, 'time_uncertain': 0}
    for t in times:
        labels[t] += 1
    counts = list(labels.values())
    ax.bar(labels.keys(), counts)
    ax.set_title('Time Distribution')
    for i in range(len(counts)):
        ax.text(i, counts[i] + 0.1, str(counts[i]), ha='center')
    ax.set_xticklabels(ax.get_xticklabels(), rotation=45)

def visualise_exclusions(ax, counts):
    labels = ['No exclusions', 'Exclusions']
    ax.bar(labels, counts)
    ax.set_title('Exclusions Distribution')
    for i in range(len(counts)):
        ax.text(i, counts[i] + 0.1, str(counts[i]), ha='center')

def visualise_treatment(ax, counts):
    labels = ['No treatment', 'Treatment']
    ax.bar(labels, counts)
    ax.set_title('Treatment Distribution')
    for i in range(len(counts)):
        ax.text(i, counts[i] + 0.1, str(counts[i]), ha='center')
