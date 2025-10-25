import json
from langchain_core.tools import tool
import sqlite3


# load documents
def read_jsonl(filename):
    res = []
    with open(filename, 'r') as f:
        for line in f:
            res.append(json.loads(line))
    return res

rules_sections = read_jsonl('sources/jsonl/all_rules.jsonl')
courses = read_jsonl('sources/jsonl/courses.jsonl')
offerings = read_jsonl('sources/jsonl/courses_offered.jsonl')

# TOOLS
@tool
def get_course_data_tool(course_codes: list[str]) -> str:
    """
    This tool fetches information about a specific course offered at IIT Delhi. The input is a list of course codes (e.g., ['COL100'], ['ELL101', 'ELP101']).
    It returns information about the courses as well as its offerings (data about course coordinator, slot, etc.) in JSON format.
    A course code consists of a three-letter alphabet code followed by a three or four digit number.
    Use this tool whenever you encounter a course code in the prompt.
    """
    codes = [code.strip().lower() for code in course_codes]
    courses_found = [course for course in courses if course['code'].lower() in codes]
    if courses_found:
        offered = [{'course_code': o['course_code'], 'year': o['year'], 'semester': o['semester'], 'instructor': o['instructor']} for o in offerings if o['course_code'].lower().startswith(tuple(codes))]
        return json.dumps({
            "courses": courses_found,
            "offerings": offered
        })
    else:
        return "Course not found."
    
programme_prompt = ''
with open('sources/programme_structures/prompt.md', 'r') as f:
    programme_prompt = f.read()

@tool
def query_sqlite_db_tool(query: str) -> str:
    """
    This tool allows you to execute SQL queries on the 'iitd_academic.db' SQLite database.
    The database contains tables with information about courses and offerings at IIT Delhi.
    Use this tool when you need to retrieve specific information that can be obtained through SQL queries.
    Ensure that your SQL queries are well-formed and relevant to the database schema.
    You are only allowed to run SELECT queries.
    Schema:
    CREATE TABLE courses (
        code TEXT PRIMARY KEY,
        name TEXT,
        description TEXT,
        hours_lecture INTEGER,
        hours_tutorial INTEGER,
        hours_practical INTEGER,
        credits INTEGER,
        prereq TEXT,
        overlap TEXT
    );
    CREATE TABLE offerings (
        id INTEGER PRIMARY KEY,
        code TEXT REFERENCES courses(code),
        year TEXT,
        semester INTEGER,
        coordinator TEXT,
        slot TEXT
    );

    Note: Avoid including the description field of courses table if it is not required.
    """
    if not query.strip().lower().startswith('select'):
        return "Invalid. Only SELECT queries are allowed."
    try:
        conn = sqlite3.connect('file:../courses.sqlite?mode=ro', uri=True)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        results = [dict(zip(columns, row)) for row in rows]
        conn.close()
        return json.dumps(results)
    except Exception as e:
        return f"An error occurred: {str(e)}"

@tool
def get_programme_structure_tool(programme_code: str) -> str:
    """
    Fetches the programme structure for a given programme code.
    The JSON object you will receive contains all the necessary information about a specific engineering discipline, including its credit requirements, course categories, and a recommended semester-wise course plan.
    Use this tool whenever you need to know about the courses in a programme code in the prompt.
    Available programme codes with their respective degrees are:
    'AM1': Applied Mechanics (B.Tech.)
    'BB1': Biochemical Engineering (B.Tech.)
    'CE1': Civil Engineering (B.Tech.)
    'CH1': Chemical Engineering (B.Tech.)
    'CH7': Chemical Engineering (Dual Degree)
    'CS1': Computer Science and Engineering (B.Tech.)
    'CS5': Computer Science and Engineering (Dual Degree)
    'EE1': Electrical Engineering (B.Tech.)
    'EE3': Electrical Engineering Power and Automation (B.Tech.)
    'ES1': Energy Engineering (B.Tech.)
    'ME1': Mechanical Engineering (B.Tech.)
    'ME2': Production and Industrial Engineering (B.Tech.)
    'MS1': Materials Science and Engineering (B.Tech.)
    'MT1': Mathematics and Computing (B.Tech.)
    'MT6': Mathematics and Computing (Dual Degree)
    'PH1': Engineering Physics (B.Tech.)
    'TT1': Textile Engineering (B.Tech.)
    """
    programme_code = programme_code.upper().strip()
    try:
        with open(f'../sources/programme_structures/{programme_code}.json', 'r') as f:
            programme_data = f.read()
        return programme_prompt + "\n\n" + programme_data
    except FileNotFoundError:
        return "Programme code not found."


@tool
def get_rules_section_tool(section_name: str) -> str:
    """
    Fetches a specific section from a given document in the rules collection.
    The available sections are given below. Mention the exact section name to retrieve it.
    General Rules:
    1.1 Background
    1.2 Departments, Centres and Schools
    1.3 Programmes Offered
    1.4 Entry Number
    1.5 Honour Code
    2.1 Course Numbering Scheme
    2.2 Credit System
    2.3 Assignment of Credits to Courses
    2.4 Earning Credits
    2.5 Description of Course Content
    2.6 Pre-requisite(s)
    2.7 Overlapping/Equivalent Courses
    2.8 Course Coordinator
    2.9 Grading System
    2.9.1 Grade points
    2.9.2 Description of grades
    2.10 Evaluation of Performance
    3.1 Registration
    3.2 Registration and Student Status
    3.3 Advice on Courses
    3.4 Validation of Registration
    3.5 Minimum Student Registration in a Course
    3.6 Late Registration
    3.7 Add/Drop, Audit and Withdrawal of Courses
    3.8 Semester Withdrawal
    3.9 Registration in Special Module Courses
    3.10 Registration for Non-graded Units
    3.11 Pre-requisite Requirement(s) for Registration
    3.12 Overlapping/Equivalent Courses
    3.13 Limits on Registration
    3.14 Registration and Fee Payment
    3.15 Continuous Absence and Registration Status
    3.16 Attendance Rule
    
    Undergraduate Rules:
    1.1.1 Overall Requirements: B.Tech.
    1.1.2 Overall Requirements: B.Des.
    1.1.3 Overall Requirements: Dual degree programmes
    1.2.1 Breakup of Degree Requirements: Earned Credit Requirements for B.Tech.
    1.2.2 Breakup of Degree Requirements: Earned Credit Requirements for B.Des.
    1.2.3 Breakup of Degree Requirements: Degree Grade Point Average (DGPA) Requirement
    1.2.4 Breakup of Degree Requirements: Audit Courses
    1.3 Non-graded Core Requirement
    1.4 Minimum and Maximum Durations for Completing Degree Requirements
    1.5 Absence During the Semester
    1.6 Conditions for Continuation of Registration, Termination/Re-start, Probation
    1.7 Scheme for Academic Advising of Undergraduate Students
    1.8 Capability Linked Opportunities for Undergraduate (B.Tech./Dual Degree) Students
    1.9 Change of Programme at the End of the First Year
    1.10 Self-study Course
    1.11 Assistantship for Dual-Degree Programmes
    1.12 Admission of UG Students to PG Programmes
    1.13 Measures for helping SC/ST Students
    1.14 Measures for helping Students with Disabilities
    2. CAPABILITY-LINKED OPTIONS FOR UNDERGRADUATE STUDENTS
    2.1.1 Minor Area in Atmospheric Sciences (Centre for
    2.1.2 Minor Area in Biological Sciences (Kusuma School
    2.1.3 Minor Area in Business Management (Department of
    2.1.4 Minor Area in Entrepreneurship (Department of
    2.1.5 Minor Area in Economics (Department of Humanities
    2.1.6 Minor Area in Computational Mechanics (Department
    2.1.7 Minor Area in Design (Department of Design)
    2.1.8 Minor Area Non Departmental Electives in Material
    2.1.9 Minor Area in Computer Science (Department of
    2.1.10 Minor Area in Cogeneration and Energy Efficiency
    2.1.11 Minor Area in Renewable Energy (Department of
    2.1.12 Minor Area in Technologies for Sustainable Rural
    2.1.13 Minor Area / Departmental Specialization in
    2.1.14 Minor Area / Departmental Specialization in Complex
    2.1.15 Minor Area / Departmental Specialization in Energy and
    2.1.16 Minor Area / Departmental Specialization in Process
    2.1.17 Minor Area / Departmental Specialization in Nano-
    2.1.18 Minor Area / Departmental Specialization in Photonics
    2.1.19 Minor Area / Departmental Specialization in Quantum
    2.1.20 Minor Area / Departmental Specialization in
    2.1.21 Interdisciplinary Specialization in Biodesign
    2.1.22 Interdisciplinary Specialization in Robotics
    2.2.1 Departmental Specialization in Applications and
    2.2.2 Departmental Specialization in Architecture and
    2.2.3 Departmental Specialization in Data Analytics and
    2.2.4 Departmental Specialization in Graphics and Vision
    2.2.5 Departmental Specialization in Software Systems (Department of Computer Science and Engineering)
    2.2.6 Departmental Specialization in Theoretical Computer Science (Department of Computer Science and Engineering)
    2.2.7 Departmental Specialization in Environmental Engineering (Department of Civil Engineering) Specialization Core
    2.2.8 Departmental Specialization in Geotechnical Engineering (Department of Civil Engineering)
    2.2.9 Departmental Specialization in Structural Engineering (Department of Civil Engineering)
    2.2.10 Departmental Specialization in Transportation Engineering (Department of Civil Engineering)
    2.2.11 Departmental Specialization in Water Resources Engineering (Department of Civil Engineering)
    2.2.12 Departmental Specialization in Automotive Design (Department of Mechanical Engineering)
    2.2.13 Departmental Specialization in Technical and Innovative Textiles (Department of Textile and Fibre Engineering)
    2.2.14 Departmental Specialization in Textile Business Management (Department of Textile and Fibre Engineering)
    2.2.15 Departmental Specialization in Appliance Engineering (Department of Electrical Engineering)
    2.2.16 Departmental Specialization in Cognitive and Intelligent Systems (Department of Electrical Engg.)
    2.2.17 Departmental Specialization in Communication Systems and Networking (Dept. of Electrical Engg.)
    2.2.18 Departmental Specialization in Electric Transportation (Department of Electrical Engineering)
    2.2.19 Departmental Specialization in Energy-Efficient Technologies (Department of Electrical Engineering)
    2.2.20 Departmental Specialization in Information Processing (Department of Electrical Engineering)
    2.2.21 Departmental Specialization in Nano-electronic and Photonic Systems (Department of Electrical Engg.)
    2.2.22 Departmental Specialization in Smart Grid and Renewable Energy (Department of Electrical Engg.)
    2.2.23 Departmental Specialization in Systems and Control (Department of Electrical Engineering)
    2.2.24 Departmental Specialization in VLSI and Embedded Systems (Department of Electrical Engineering)
    2.2.25 Departmental Specialization in Polymeric Materials (Department of Materials Science and Engineering)
    2.1.26 Departmental Specialization in Metallurgy (Department of Materials Science and Engineering)
    3. NON-GRADED CORE FOR UNDERGRADUATE STUDENTS
    3.1 Introduction to Engineering and Programme
    3.2 Language and Writing Skills
    3.3 NCC/ NSO/ NSS
    3.4 Professional Ethics and Social Responsibility
    3.5 Communication Skills / Seminar
    3.6 Design / Practical Experience
    3.6.1 Management of Non-graded DPE Units
    3.6.2.1 Specialized Courses Related to Design / Practical Experience (Maximum 2 Units)
    3.6.2.2 Semester / Summer / Winter Projects Under the Guidance of Institute Faculty (Maximum 2 Units)
    3.6.2.3 Regular Courses with Optional Design / Practical Experience Component (Maximum 2 Units)
    3.6.2.4 Summer Internships (Maximum 2 Units)
    3.6.2.5 One-Semester Internship (Maximum 5 Units)
    3.6.2.6 One Time Design / Practical Experience Module (1 Unit)
    3.6.3 Rules Governing Internship
    3.6.3.1 Registration Procedure for Internships
    3.7 Overlapping Activities
    
    Postgraduate Rules:
    1.1 Degree Requirements
    1.2 Continuation Requirements
    1.3 Minimum Student Registration for a Programme
    1.4 Lower and Upper Limits for Credits Registered
    1.5 Audit Courses for PG Students
    1.6 Award of D.I.I.T. to M.Tech./MBA Students
    1.7 Regulations for Part-time Students
    1.8 Leave Rules for P.G. D.I.I.T., M.Des., M.Tech. and M.S. (Research)
    1.9 Assistantship Requirements
    1.10 Summer Registration
    1.11 Master of Science (Research) Regulations
    1.12 Migration from one PG programme to another PG Programme of the Institute
    1.13 Doctor of Philosophy (Ph.D.) Regulations
    1.13.1 Course requirements
    1.13.2 Time limit
    1.13.3 Leave regulations
    1.13.4 Attendance requirements for assistantship
    1.13.5 Further regulations governing Ph.D. students
    ---
    For any general query regarding 'minor degree', use the tool with section '2. CAPABILITY-LINKED OPTIONS FOR UNDERGRADUATE STUDENTS' as input.
    For a minor degree or specialisation in any specific department, call the tool on the respective sub-section of 2.1 or 2.2.
    """
    sections = [sec for sec in rules_sections if sec['section'].lower().strip() == section_name.lower().strip()]
    print(f'---get_rules_section_tool called with section_name="{section_name}"---')
    print("Found sections:")
    print(sections)
    if sections:
        return json.dumps(sections[0])
    else:
        return "Section not found."

# print(query_sqlite_db_tool('SELECT * from courses WHERE code LIKE "COL1%"'))