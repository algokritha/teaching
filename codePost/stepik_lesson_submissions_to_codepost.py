#!/usr/bin/env python3.7
'''
Given a Stepik lesson submission report, create a codePost assignment with submissions and scores via codePost API
Niema Moshiri 2019
'''
from csv import reader
from datetime import datetime,timezone
from io import StringIO
from os.path import realpath
from subprocess import PIPE,run
from tempfile import NamedTemporaryFile
from xlrd import open_workbook
import codepost
EXT = {'java':'java', 'python':'py'}
GRADER = "niemamoshiri@gmail.com" # all finalized assignments must have a "grader"
SCRIPT_PATH = '/'.join(realpath(__file__).split('/')[:-1])
CHECKSTYLE_PATH = "%s/../checkstyle" % SCRIPT_PATH

# main function
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-r', '--roster', required=True, type=str, help="Roster (TSV) (Last, First, Email, PID, Stepik, iClicker, Grade ID)")
    parser.add_argument('-s', '--submissions', required=True, type=str, help="Stepik Lesson Submission Report (XLSX)")
    parser.add_argument('-d', '--deadline', required=True, type=str, help="Deadline (MM/DD/YYYY HH:MM ±HHMM)")
    parser.add_argument('-c', '--course_id', required=True, type=int, help="codePost Course ID")
    parser.add_argument('-a', '--assignment_name', required=True, type=str, help="codePost Assignment Name")
    parser.add_argument('-p', '--point_total', required=True, type=int, help="Total Possible Number of Points")
    parser.add_argument('-pc', '--point_cap', required=False, type=int, default=float('inf'), help="Point Cap")
    parser.add_argument('-l', '--language', required=False, type=str, default=None, help="Language (%s)" % ', '.join(sorted(EXT.keys())))
    parser.add_argument('-nc', '--no_checkstyle', action='store_true', help="Do not run checkstyle")
    parser.add_argument('-u', '--update', action='store_true', help="Update assignment (instead of creating a new one)")
    args = parser.parse_args()
    assert args.point_cap >= 0, "Point cap cannot be negative"
    if args.language is None:
        file_ext = 'txt'
    else:
        assert args.language.lower() in EXT, "Invalid language: %s (valid: %s)" % (args.language, ', '.join(sorted(EXT.keys())))
        file_ext = EXT[args.language.lower()]
    deadline = datetime.strptime(args.deadline, "%m/%d/%Y %H:%M %z")

    # parse roster
    print("Parsing roster: %s" % args.roster)
    email_to_stepik = dict()
    for l in open(args.roster):
        if l.startswith("Last Name\t"):
            continue
        last,first,email,pid,stepik = [v.strip() for v in l.split('\t')][:5]
        assert email not in email_to_stepik, "Duplicate Email: %s" % email
        try:
            email_to_stepik[email] = int(stepik)
        except:
            email_to_stepik[email] = -1 # dummy missing value
    stepik_to_email = {email_to_stepik[email]:email for email in email_to_stepik}
    if -1 in stepik_to_email:
        del stepik_to_email[-1] # delete dummy missing value
    passed = {email:dict() for email in email_to_stepik}
    print("Loaded %d students from roster." % len(passed))

    # parse submission report
    print("Parsing Stepik lesson submission report: %s" % args.submissions)
    subs_by_email = {email:dict() for email in email_to_stepik}
    if args.submissions.split('.')[-1].lower() == 'csv':
        subs_lines = [line for line in reader(StringIO(open(args.submissions).read().replace('\x00','')))]
    else:
        subs = open_workbook(args.submissions).sheet_by_index(0)
        subs_lines = [subs.row_values(rowx) for rowx in range(subs.nrows)]
    for sub_id,step_id,user_id,last,first,attempt_time,sub_time,status,dataset,clue,reply,reply_clear,hint in subs_lines:
        if sub_id == "submission_id":
            continue # header line
        step_id = int(float(step_id)); user_id = int(float(user_id))
        try:
            reply = eval(reply)
        except:
            pass # sometimes weird strings
        sub_time = datetime.fromtimestamp(float(sub_time), timezone.utc)
        if user_id not in stepik_to_email or status == 'wrong' or sub_time > deadline:
            continue
        if 'text' in reply and ('attachments' in reply or '<p>' in str(reply)):
            continue
        email = stepik_to_email[user_id]
        passed[email][step_id] = reply
    print("Loaded submissions.")

    # load codePost configuration and course
    codepost_config = codepost.util.config.read_config_file()

    # update codePost assignment,
    if args.update:
        print("Loading codePost course...", end=' ', flush=True)
        while True:
            try:
                course = codepost.course.retrieve(id=args.course_id)
                break
            except:
                pass
        print("done")
        print("Finding assignment (%s)..." % args.assignment_name, end=' ', flush=True)
        codepost_assignment = None
        for a in course.assignments:
            while True:
                try:
                    curr = codepost.assignment.retrieve(id=a.id)
                    break
                except:
                    pass
            if curr.name.strip() == args.assignment_name.strip():
                codepost_assignment = curr; break
        if codepost_assignment is None:
            raise ValueError("Assignment not found: %s" % args.assignment_name)
        print("done")

    # or create codePost assignment
    else:
        print("Creating new codePost assignment (%s)..." % args.assignment_name, end=' ')
        while True:
            try:
                codepost_assignment = codepost.assignment.create(name=args.assignment_name, points=args.point_total, course=args.course_id)
                break
            except Exception as e:
                pass
        print("done")

    # upload submissions
    print("Uploading %d student submissions to codePost..." % len(passed))
    for student_num,email in enumerate(passed.keys()):
        print("Student %d of %d (%s)..." % (student_num+1, len(passed), email), end='\r')
        student_points = min(len(passed[email]), args.point_cap)
        while True:
            try:
                codepost_sub = codepost.submission.create(assignment=codepost_assignment.id, students=[email], isFinalized=True, grader=GRADER)
                break
            except Exception as e:
                pass
        for step_id in sorted(passed[email].keys()):
            if 'code' not in passed[email][step_id]:
                continue
            curr_code = passed[email][step_id]['code'].strip()
            while True:
                try:
                    code_file = codepost.file.create(name="%d.%s"%(step_id,file_ext), code=curr_code, extension=file_ext, submission=codepost_sub.id)
                    break
                except Exception as e:
                    pass
            if not args.no_checkstyle:
                tmpfile = NamedTemporaryFile(mode='w'); tmpfile.write(curr_code); tmpfile.flush()
                p = run(['java', '-jar', '%s/checkstyle.jar'%CHECKSTYLE_PATH, '-c', '%s/style_checks.xml'%CHECKSTYLE_PATH, tmpfile.name], stdout=PIPE, stderr=PIPE)
                curr_comments = {l.strip().split(': ')[-1].split('[')[0].split('(')[0].strip() for l in p.stdout.decode().strip().splitlines() if l.strip()[-1] == ']'}
                if len(curr_comments) != 0:
                    while True:
                        try:
                            curr_comment = codepost.comment.create(text='\n\n'.join(curr_comments), startChar=0, endChar=0, startLine=0, endLine=0, file=code_file.id, pointDelta=0, rubricComment=None)
                            break
                        except Exception as e:
                            pass
        while True:
            try:
                grade_file = codepost.file.create(name="grade.txt", code="Grade: %d/%d"%(student_points,args.point_total), extension='txt', submission=codepost_sub.id)
                break
            except Exception as e:
                pass
        point_delta = args.point_total - student_points # codePost currently assumes subtractive points; update this when they integrate additive
        while True:
            try:
                grade_comment = codepost.comment.create(text='points', startChar=0, endChar=0, startLine=0, endLine=0, file=grade_file.id, pointDelta=point_delta, rubricComment=None)
                break
            except Exception as e:
                pass
    print("Successfully uploaded %d student submissions" % len(passed))
