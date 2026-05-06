"""
Script to remove historical content from clinical notes using three cleaning rules:

1. Date separators (e.g., "FU today")
2. Duplicate copy/paste chunks (text that was carried over from the previous note)
3. Vital signs and delimiters (e.g., "BP", "---", "***")

Data assumptions:
- Each clinical note file is named using the pattern: `[pid]-[gender][age]-[visit_date].txt`
  where:
    - pid           : patient identifier (e.g., "001")
    - gender        : "M" or "F"
    - age           : integer (e.g., "45")
    - visit_date    : date in YYYYMMDD format (e.g., "20240315")
  
  Example: `001-M45-20240315.txt`

- File content structure:
Note
[clinical note text content]
Management Plan:
[optional management plan content]

Note: The script preserves the "Management Plan:" section and removes boilerplate history from the main note content.
"""


from datetime import datetime
from dateutil.relativedelta import relativedelta
import re
import os
import shutil

TODAY_INDICATORS = ['(FU|Fu|fu)\s.*[T|t]oday', '^[T|t]oday(\s*[^\w\s])?$', '^[T|t]oday[^\n]*(BP|Bp|bp|blood pressure)']
VITAL_SIGN_INDICATORS = '(^|\n)BW[^\n]*\n|(^|\n)[^\n]*\d{2,3}\s*kg[^\n]*\n|(^|\n)((BP|Bp|bp|blood pressure)[^\n]*)?\d{2,3}\s*\/\s*\d{2,3}[^\d][^\n]*\n|(^|\n)[^\n]*(24 hour|24 hr|DNA|dna|UP\s|C3|C4|c3|c4|UPC)[^\n]*\n'
DELIMIETER_INDICATORS = ['^[\=]+$', '^[\*]+$', '^[\.]+$', '^[\-]+$', '^[_]+$']
DAYS_CUTOFF = 30


def split_by_date_indicator(text, date_today):
    date_today = datetime.strptime(date_today, "%Y%m%d")
    lines = text.split('\n')
    new_lines = lines
    recent_date = None
    ## search for dates first and keep it if it's within DAYS_CUTOFF (30 days)
    for i, line in enumerate(lines):
        match = re.search('\d{1,2}\/\d{1,2}\/\d{4}|\d{1,2}\/\d{4}', line)
        if match:
            date = match.group()
            try:
                if len(date.split('/')) < 3: # if only date and month
                    date = datetime(int(date.split('/')[-1]), int(date.split('/')[0]), 1) + relativedelta(day=31) # last day of month
                else:
                    date = datetime.strptime(date, "%d/%m/%Y")
            except:
                continue
            days_diff = (date_today - date).days
            if 0 <= days_diff <= DAYS_CUTOFF:
                recent_date = i
                break
    cutoff_line = None
    for sep in TODAY_INDICATORS: # sep priority in order
        for i, line in enumerate(lines):
            if re.search(sep, line):
                cutoff_line = i # keep finding till the last occurence
        if cutoff_line:
            break

    # keep whichever comes first: 'today' or recent date
    if recent_date and cutoff_line and recent_date < cutoff_line:
        cutoff_line = recent_date
    if cutoff_line:
        print(f'REMOVING {lines[cutoff_line]}')
        new_lines = [lines[0]] + lines[cutoff_line:]

    text = '\n'.join(new_lines)
    return text, bool(cutoff_line)

def detect_duplicate_chunk(text1, text2):
    lines1 = text1.split('\n')
    lines2 = text2.split('\n')
    chunks = []
    
    # skip first line 'Note'
    i = 1
    while i < len(lines1)-1:
        if i > 1: # start of chunk must be the first line
            break
        found = False
        j = 1
        while j < len(lines2)-1:
            # check if two consecutive lines are the same
            if j > 1: # start of chunk must be the first line
                break
            if lines1[i].replace(' ', '') == lines2[j].replace(' ', '') and lines1[i+1].replace(' ', '') == lines2[j+1].replace(' ', ''):
                chunk = [lines2[j], lines2[j+1]]
                # find remaining chunk
                k = 2
                while i+k < len(lines1) and j+k < len(lines2) and lines1[i+k].replace(' ', '') == lines2[j+k].replace(' ', ''):
                    chunk.append(lines2[j+k])
                    k += 1
                # don't remove the last if it is a delimiter separator
                if re.search('|'.join(DELIMIETER_INDICATORS), chunk[-1]):
                    chunk = chunk[:-1]
                chunks.append('\n'.join(chunk))
                i += k
                found = True
                break
            j += 1
        if not found:
            i += 1
    return chunks

def detect_vital_signs_and_delimiters(text, date_today):
    date_today = datetime.strptime(date_today, "%Y%m%d")
    lines = text.split('\n')
    text = '\n'.join(lines[1:]) # Keep first line 'Note'

    def search_date_in_line(line):
        date_match = re.search(r'\d{1,2}\/\d{1,2}\/\d{4}', line)
        if not date_match:
            date_match = re.search(r'\d{1,2}\/\d{4}', line)
        if not date_match:
            return None
        date = line[date_match.start():date_match.end()]
        try:
            if len(date.split('/')) < 3:
                date = datetime(int(date.split('/')[-1]), int(date.split('/')[0]), 1) + relativedelta(day=31) # last day of month
            else:
                date = datetime.strptime(date, "%d/%m/%Y")
        except:
            return None
        return date

    recent_date = None
    ## search for dates first and keep it if it's within 30 days
    matches = re.finditer('\n[^\n]*\d{1,2}\/\d{1,2}\/\d{4}[^\n]*\n|\n[^\n]*\d{1,2}\/\d{4}[^\n]*\n', text)
    for match in matches:
        line_start, line_end = match.start(), match.end()
        date = search_date_in_line(text[line_start:line_end])
        if date and 0 <= (date_today - date).days <= DAYS_CUTOFF:
            recent_date = (match.start(), match.end())
            break

    pattern = VITAL_SIGN_INDICATORS
    for delimiter in DELIMIETER_INDICATORS:
        pattern += '|' + delimiter.replace('^', '(^|\n)').replace('$', '($|\n)')
    match_start, match_end = None, None
    matches = re.finditer(pattern, text)
    for match in matches:
        line_start, line_end = match.start(), match.end()
        date = search_date_in_line(text[line_start:line_end])
        if not date or (date_today - date).days <= DAYS_CUTOFF:
            match_start, match_end = line_start, line_end
            break
    if match_start and recent_date and recent_date[0] < match_start:
        match_start, match_end = recent_date[0], recent_date[1]
    if match_start:
        print(f"REMOVING {text[match_start:match_end].strip()}")
        text = text[match_start:]
    text = lines[0] + '\n' + text
    return text, bool(match_start)

def main():
    # Remove history using rule-based methods
    files = os.listdir(source_dir)
    pids = set([f.split('-')[0] for f in files])
    removed = set() # remove files if empty after history removal

    files_split_by_date = []
    files_split_by_VS_delimiter = []
    files_rm_chunks = []
    count_nosplit = 0

    for pid in list(pids):
        date_dict={}
        for filename in files:
            if filename.startswith(pid):
                date_dict[filename] = filename.split('.')[0].split('-')[-1] # date
        ## sort date_dict by date (the value in dictionary)
        datedict_sorted={k: v for k, v in sorted(date_dict.items(), key=lambda item: datetime.strptime(item[1], "%Y%m%d"))}

        files_sorted = list(datedict_sorted.keys())
        # write first file to new_dir first
        first_file = files_sorted[0]
        with open(source_dir+first_file) as f, open(new_dir+first_file, 'w') as fout:
            date_today = first_file.split('.')[0].split('-')[-1]
            text = f.read()
            text, found = split_by_date_indicator(text, date_today=date_today)
            if found:
                files_split_by_date.append(first_file)
            if not found:
                text, found = detect_vital_signs_and_delimiters(text, date_today=date_today)
                if found:
                    files_split_by_VS_delimiter.append(first_file)
                if not found:
                    count_nosplit += 1
            fout.write(text.replace('\n\n', '\n'))
            f.close()
            fout.close()

        #1. Detect separation indicators, chunk of copy/paste notes
        for i in range(len(files_sorted)-1):
            file1, file2 = files_sorted[i], files_sorted[i+1]
            print(file2)

            with open(source_dir+file1) as f1, open(source_dir+file2) as f2:
                text1, text2 = f1.read(), f2.read()
                date_today = file2.split('.')[0].split('-')[-1]

                #1a. Split by separate indicators, e.g. FU today, etc.
                text2, found = split_by_date_indicator(text2, date_today=date_today)
                if found:
                    files_split_by_date.append(file2)

                if not found:
                #1b. Detect duplicate texts; only remove if they start from first line
                    chunks = detect_duplicate_chunk(text1, text2)
                    if chunks:
                        files_rm_chunks.append(file2)
                    for chunk in chunks:
                        print('Detected chunk of copy/paste text. Deleting...')
                        text2 = text2.replace(chunk, '') ## write file2

                #1c. Detect vital signs / delimiters
                    text2, found = detect_vital_signs_and_delimiters(text2, date_today=date_today)
                    if found:
                        files_split_by_VS_delimiter.append(file2)
                    if not found:
                        count_nosplit += 1

                if text2.replace('Note\n', '').strip().split('Management Plan')[0]:
                    with open(new_dir+file2, 'w') as fout:
                        fout.write(text2.replace('\n\n', '\n'))
                        fout.close()
                else:
                    print(f'WARNING: {file2} removed due to being empty')
                    removed.add(file2)

                f1.close()
                f2.close()
    print('All removed files due to being empty after history removal', removed)


if __name__ == '__main__':
    root_dir = './'
    source_dir = root_dir + 'deidentified_notes/'
    new_dir = root_dir + 'history_removed_notes/'
    shutil.rmtree(new_dir, ignore_errors=True)
    os.makedirs(new_dir, exist_ok=True)
    main()
