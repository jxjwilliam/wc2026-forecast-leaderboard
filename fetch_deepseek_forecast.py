"""
fetch_deepseek_forecast.py — One-time: call DeepSeek API to generate
World Cup 2026 match predictions and save to data/deepseek.md.

This is the "static forecast file" for DeepSeek, matching the pattern of
chatgpt.md, gemini.md, etc. The file is generated once via API call then
parsed by parse_forecasts.py alongside the other models.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from parse_forecasts import CANONICAL_MATCHES

load_dotenv()

DATA_DIR = Path("data")
OUTPUT_FILE = DATA_DIR / "deepseek.md"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


def _build_prompt() -> str:
    """Build a prompt asking DeepSeek to predict all 72 group-stage matches."""
    groups: dict[str, list[str]] = {}
    for m in CANONICAL_MATCHES:
        g = m["group"]
        if g not in groups:
            groups[g] = []
        groups[g].append(f"{m['home']} vs {m['away']}")

    prompt_parts = [
        "You are a football expert. Predict the score for each 2026 World Cup "
        "group-stage match below. Output ONLY a markdown table with columns: "
        "Group | Match | Score\n\n"
        "Rules:"
        "\n- Each match gets exactly one score (home-away, e.g. 2-1)"
        "\n- Be realistic based on team strength, FIFA ranking, form"
        "\n- Draws are possible (e.g. 1-1)"
        "\n- No explanations, no commentary — just the table"
        "\n- Use | as column separator"
        "\n- Match format: \"TeamA vs TeamB\" — same as the input"
        "\n\nMatches by group:\n"
    ]

    for group_letter in sorted(groups.keys()):
        prompt_parts.append(f"\n## Group {group_letter}\n")
        for match_str in groups[group_letter]:
            prompt_parts.append(f"| {group_letter} | {match_str} | ")

    return "\n".join(prompt_parts)


def _parse_response(text: str) -> str:
    """Extract and clean the table from DeepSeek's response into data/deepseek.md format."""
    lines = text.strip().split("\n")
    # Keep only lines that look like table rows: | X | Y | Z |
    table_lines = ["# DeepSeek 2026 World Cup Predictions\n"]
    header_written = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if len(cells) >= 3:
                if not header_written:
                    table_lines.append("| Group | Match | Score |\n| --- | --- | --- |\n")
                    header_written = True
                # Reconstruct clean row
                row = f"| {cells[0]} | {cells[1]} | {cells[2]} |\n"
                table_lines.append(row)
    return "".join(table_lines)


def main() -> None:
    if not DEEPSEEK_API_KEY:
        print("ERROR: DEEPSEEK_API_KEY not set in .env")
        return

    print("=== Fetching DeepSeek forecast ===")
    print(f"Model: {DEEPSEEK_MODEL}")
    print(f"Matches to predict: {len(CANONICAL_MATCHES)}")

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    prompt = _build_prompt()

    print("Sending prompt to DeepSeek API...")
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4096,
    )

    content = response.choices[0].message.content
    if not content:
        print("ERROR: Empty response from DeepSeek")
        return

    print(f"Response length: {len(content)} chars")
    print(f"Tokens used: {response.usage.total_tokens if response.usage else 'N/A'}")

    table = _parse_response(content)
    output_path = Path(OUTPUT_FILE)
    DATA_DIR.mkdir(exist_ok=True)
    output_path.write_text(table, encoding="utf-8")

    row_count = table.count("\n| ") - 1  # subtract header row
    print(f"\nSaved {row_count} predictions to {output_path}")
    print("DeepSeek forecast file created.")


if __name__ == "__main__":
    main()
