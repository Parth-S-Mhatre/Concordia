"""Generate 100-record demo datasets preserving the overlap design.

Each file gets exactly 100 rows:
  - 90 LINKED persons present in all 4 sources (different column names,
    variant emails in B, no email at all in C -> forces progressive
    enrichment via phone/username/member_id bridges).
  - 10 SOURCE-UNIQUE persons per file (demonstrates no-match handling:
    they become new entities until a future dataset links them).

Hero rows (john/jane/bob/alice/charlie/david/eve/frank) keep their original
values so the documented `john@example.com` demo flow keeps working.
"""

import csv
from pathlib import Path

OUT = Path(__file__).resolve().parent

FIRST = ["Aarav", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna", "Ishaan",
         "Rohan", "Kabir", "Ananya", "Diya", "Aadhya", "Myra", "Sara",
         "Ira", "Priya", "Neha", "Rahul", "Amit", "Sneha"]
LAST = ["Sharma", "Verma", "Patel", "Iyer", "Reddy", "Nair", "Gupta",
        "Mehta", "Khan", "Singh", "Das", "Kulkarni", "Joshi", "Chopra",
        "Bose", "Menon", "Rao", "Pillai", "Yadav", "Mishra"]
COMPANIES = ["ABC Pvt Ltd", "XYZ Corp", "Tech Solutions", "Global Inc",
             "StartupXYZ", "BrightEdge Labs", "NovaTech", "UrbanNest",
             "FinEdge", "MediCore", "EduSpark", "AgroPure", "TravelNest",
             "FoodKraft", "StyleHub"]
CITIES = ["Mumbai", "Delhi", "Bangalore", "Chennai", "Pune", "Hyderabad",
          "Kolkata", "Ahmedabad", "Jaipur", "Kochi", "Indore", "Lucknow"]

# (person_id, first, last, email_a, phone, username, member, company, city)
HEROES = [
    (1, "John", "Doe", "john@example.com", "9876543210", "johndoe", "MEM1042", "ABC Pvt Ltd", "Mumbai"),
    (2, "Jane", "Smith", "jane@example.com", "9876543211", "janesmith", "MEM1043", "XYZ Corp", "Delhi"),
    (3, "Bob", "Wilson", "bob@example.com", "9876543212", "bobwilson", "MEM1044", "Tech Solutions", "Bangalore"),
    (4, "Alice", "Brown", "alice@example.com", "9876543213", "alicebrown", "MEM1045", "Global Inc", "Chennai"),
]
# B-variant emails for heroes (original demo values)
HERO_B_EMAIL = {1: "john2@example.com", 2: "jane2@example.com",
                3: "bob2@example.com", 4: "alice2@example.com"}
# Source-unique originals: charlie (A-only), david (B-only), eve (C-only), frank (D-only)
CHARLIE = (101, "Charlie", "Davis", "charlie@example.com", "9876543214")
DAVID = (111, "David", "Lee", "david@example.com", "9876543215", "Pune")
EVE = (121, "evewilson", "9876543216", "StartupXYZ")
FRANK = (131, "MEM1046", "frank@example.com", "frankwilson")


def build_people():
    people = []  # linked persons 1..90
    used_names = set()
    for pid, first, last, email, phone, user, mem, comp, city in HEROES:
        people.append({"id": pid, "first": first, "last": last,
                       "email_a": email, "phone": phone, "username": user,
                       "member": mem, "company": comp, "city": city})
        used_names.add((first, last))
    pid = 5
    for first in FIRST:
        for last in LAST:
            if len(people) >= 90:
                break
            if (first, last) in used_names:
                continue
            used_names.add((first, last))
            email_a = f"{first}.{last}@example.com".lower()
            phone = f"982{pid:07d}"
            username = f"{first}{last}".lower()
            people.append({"id": pid, "first": first, "last": last,
                           "email_a": email_a, "phone": phone,
                           "username": username, "member": f"MEM{1100 + pid}",
                           "company": COMPANIES[pid % len(COMPANIES)],
                           "city": CITIES[pid % len(CITIES)]})
            pid += 1
        if len(people) >= 90:
            break
    assert len(people) == 90, len(people)
    return people


def b_email(p):
    if p["id"] in HERO_B_EMAIL:
        return HERO_B_EMAIL[p["id"]]
    return f"{p['first']}{p['id']}@example.com".lower()


def unique_people(start, count, prefix):
    """Source-unique persons (appear in one file only)."""
    out, used, pid = [], set(), start
    fi = 0
    while len(out) < count:
        first, last = FIRST[(fi * 7 + 3) % len(FIRST)], LAST[(fi * 11 + 5) % len(LAST)]
        fi += 1
        if (first, last) in used:
            continue
        used.add((first, last))
        out.append({"id": pid, "first": first, "last": last,
                    "email_a": f"{first}.{last}{pid}@example.com".lower(),
                    "phone": f"{prefix}{pid:07d}",
                    "username": f"{first}{last}{pid}".lower(),
                    "member": f"MEM{2000 + pid}",
                    "company": COMPANIES[pid % len(COMPANIES)],
                    "city": CITIES[pid % len(CITIES)]})
        pid += 1
    return out


def write_csv(name, header, rows):
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"{name}: {len(rows)} records")


def main():
    linked = build_people()

    a_rows = [[p["email_a"], f"{p['first']} {p['last']}", p["phone"]] for p in linked]
    a_rows.append([CHARLIE[3], "Charlie Davis", CHARLIE[4]])  # A-only original
    for p in unique_people(102, 9, "983"):
        a_rows.append([p["email_a"], f"{p['first']} {p['last']}", p["phone"]])
    write_csv("database_a.csv", ["email", "full_name", "mobile_number"], a_rows)

    b_rows = [[b_email(p), f"{p['first']} {p['last']}", p["phone"], p["city"]] for p in linked]
    b_rows.append([DAVID[3], f"{DAVID[1]} {DAVID[2]}", DAVID[4], DAVID[5]])
    for p in unique_people(112, 9, "984"):
        b_rows.append([p["email_a"], f"{p['first']} {p['last']}", p["phone"], p["city"]])
    write_csv("database_b.csv", ["email_id", "name", "contact_no", "address"], b_rows)

    c_rows = [[p["username"], p["phone"], p["company"]] for p in linked]
    c_rows.append([EVE[1], EVE[2], EVE[3]])
    for p in unique_people(122, 9, "985"):
        c_rows.append([p["username"], p["phone"], p["company"]])
    write_csv("database_c.csv", ["username", "phone", "company"], c_rows)

    d_rows = [[p["member"], p["email_a"], p["username"]] for p in linked]
    d_rows.append([FRANK[1], FRANK[2], FRANK[3]])
    for p in unique_people(132, 9, "986"):
        d_rows.append([p["member"], p["email_a"], p["username"]])
    write_csv("database_d.csv", ["member_id", "email", "username"], d_rows)


if __name__ == "__main__":
    main()
