import subprocess, re, datetime, sys

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()

changed = sh("git diff --name-only origin/main...HEAD").splitlines()

results = []
ok = True

def check(name, passed, detail=""):
    global ok
    ok = ok and passed
    results.append(f"- {'✅' if passed else '❌'} {name}" + (f": {detail}" if detail else ""))

# 1. only README + one new image file changed
img_ext = (".png", ".jpg", ".jpeg", ".gif")
non_readme_img = [f for f in changed if f != "README.md" and not f.lower().endswith(img_ext)]
check("No other git changes", len(non_readme_img) == 0, ", ".join(non_readme_img))

imgs = [f for f in changed if f.lower().endswith(img_ext)]
check("Exactly one new image added", len(imgs) == 1, str(imgs))

# 2. README diff: exactly one line added, none removed
readme_diff = sh("git diff origin/main...HEAD -- README.md")
added = [l for l in readme_diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
removed = [l for l in readme_diff.splitlines() if l.startswith("-") and not l.startswith("---")]
check("Only one line added to README, none removed", len(added) == 1 and len(removed) == 0,
      f"{len(added)} added, {len(removed)} removed")

# 3. valid markdown — new line should be an image embed referencing the new file
if added and imgs:
    line = added[0][1:].strip()
    check("New README line is a valid image embed matching the new file",
          bool(re.search(re.escape(imgs[0].split("/")[-1]), line)) and line.startswith("!["),
          line)
elif added:
    check("New README line is a valid image embed matching the new file", False, "no image file found")

# 4. image lives in <Year>/<Month Name>/ folder, current month (1-day forgiveness)
MONTHS = ["January","February","March","April","May","June","July",
          "August","September","October","November","December"]

if imgs:
    p = imgs[0]
    parts = p.split("/")
    today = datetime.date.today()
    valid = {(str(today.year), MONTHS[today.month - 1])}
    if today.day == 1:
        prev = today.replace(day=1) - datetime.timedelta(days=1)
        valid.add((str(prev.year), MONTHS[prev.month - 1]))
    if len(parts) >= 3:
        year, month = parts[0], parts[1]
        check("Image is in correct Year/Month folder (or forgiven)",
              (year, month) in valid, f"found {year}/{month}, expected one of {valid}")
    else:
        check("Image is inside a Year/Month folder", False, p)

with open("comment.md", "w") as f:
    f.write("## Dino PR Check Results\n\n")
    f.write("\n".join(results))
    f.write(f"\n\n**Overall: {'✅ All checks passed' if ok else '❌ Some checks failed'}**")

sys.exit(0 if ok else 1)zzz
