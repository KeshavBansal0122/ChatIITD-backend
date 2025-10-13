The JSON object below contains all the necessary information about a specific engineering discipline, including its credit requirements, course categories, and a recommended semester-wise study plan.

### Root Level Fields
* `code` (String): A short, unique identifier for the academic program. For example, "ME2" represents "B. Tech. in Production and Industrial Engineering".
* `name` (String): The full, formal name of the degree program.
* `dual` (Boolean): A flag indicating whether the program is a dual degree. `false` means it is a standard 4-year B.Tech. program.
* `credits` (Object): An object that defines the credit distribution required for graduation. The total number of credits required is the sum of the values in this object.
* `courses` (Object): An object containing arrays of course codes, categorized by their type (e.g., Departmental Core, Programme-Linked).
* `recommended` (Array of Arrays): A 2D array that lays out the recommended sequence of courses over 8 semesters.

---

### Detailed Field Explanations

#### 1. The `credits` Object
This object itemizes the number of credits a student must earn from different categories of courses.

* `BS`: Basic Sciences (e.g., Physics, Chemistry, Math).
* `EAS`: Engineering Arts and Science (e.g., Introduction to Computer Science, Engineering Mechanics).
* `HuSS`: Humanities and Social Sciences.
* `PL`: Programme-linked Courses (courses that bridge institute-level core science with departmental specialization).
* `DC`: Departmental Core (mandatory courses for the specific engineering discipline).
* `DE`: Departmental Electives (a pool of specialized courses from which students must choose a certain number of credits).
* `OC`: Open Category Courses (electives that can be taken from any department in the institute).

---

#### 2. The `courses` Object
This object provides the specific course codes for the core and elective categories of the department.

* `PL`: An array of strings, where each string is a course code for a Programme-Linked course.
* `DC`: An array of strings, listing all mandatory Departmental Core course codes.
* `DE`: An array of strings, listing all available Departmental Elective course codes.

---

#### 3. The `recommended` Array
This is a critical field that represents the suggested path through the program.

* It is an array containing exactly 8 inner arrays.
* Each inner array corresponds to a semester, starting from Semester 1.
    * `recommended[0]` is Semester 1.
    * `recommended[1]` is Semester 2.
    * ...and so on, up to `recommended[7]` for Semester 8.
* Each inner array contains the course codes (as strings) that a student is advised to take in that particular semester.
* Placeholder codes like "HUL2XX", "DE1", "OC1" are used to signify that a student should take a Humanities elective, the first Departmental Elective, or the first Open Category elective, respectively, in that semester.