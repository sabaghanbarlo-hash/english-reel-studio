"""Diagnostic: run the AI planner once on a sample script and print what it produced."""
import sys

sys.path.insert(0, ".")
from reel import planner  # noqa: E402

SCRIPT = (
    "Your brain hates unfinished things. Psychologists call it the Zeigarnik effect: open tasks keep nagging at "
    "your mind until you close them. That is why you replay an argument at 2 a.m. The fix is surprisingly simple. "
    "Write down exactly what is unresolved, and the next step you will take. "
    "Your mind relaxes once it trusts there is a plan. What is the one thing you keep carrying around?"
)

plan = planner._plan_llm(SCRIPT)
if not plan:
    sys.exit("AI planner unavailable (see warnings above).")
print("SOURCE:", plan["source"], "| scenes:", len(plan["shots"]))
print("CAPTION:", plan["caption"], plan["hashtags"])
print("QUESTION:", plan["pinned_question"])
for s in plan["shots"]:
    print("-", s["delivery"], "|", s["scene"], "/", s["pose"], "/", s["emotion"], "|", repr(s["label"]), "|", s["narration"])
