from pathlib import Path

import pytest
from app.services.answer_quality import assess_answer

GOOD = (Path(__file__).parent / "fixtures" / "shear_force_answer.md").read_text(encoding="utf-8")


def test_well_structured_shear_force_answer_is_readable() -> None:
    quality = assess_answer(GOOD)

    assert quality.issues == []
    assert quality.readable
    assert quality.sections == [
        "Overview",
        "Key concepts",
        "Worked example",
        "Common mistakes",
        "Check yourself",
        "Study checklist",
    ]


def test_concepts_are_the_subheadings_of_key_concepts() -> None:
    assert assess_answer(GOOD).concepts == [
        "Internal shear force",
        "Sign convention",
        "Load, shear and moment relations",
        "Point loads and jumps",
    ]


def test_inline_citations_are_counted() -> None:
    assert assess_answer(GOOD).inline_citations == 7


def test_display_math_does_not_count_as_a_long_paragraph() -> None:
    assert assess_answer(GOOD).longest_paragraph_words < 60


def test_missing_sections_are_reported() -> None:
    answer = GOOD.replace("## Common mistakes", "## Pitfalls").replace(
        "## Study checklist", "## Next steps"
    )

    assert "missing sections: Common mistakes, Study checklist" in assess_answer(answer).issues


def test_too_few_concepts_are_reported() -> None:
    start = GOOD.index("### Sign convention")
    end = GOOD.index("## Worked example")
    answer = GOOD[:start] + GOOD[end:]

    assert "only 1 concepts explained" in assess_answer(answer).issues


def test_repeated_concept_headings_are_reported() -> None:
    answer = GOOD.replace("### Point loads and jumps", "### Sign convention")

    assert "repeated concept headings" in assess_answer(answer).issues


def test_wall_of_text_is_reported() -> None:
    wall = " ".join(["Shear force is internal and acts along the section."] * 20)
    answer = GOOD.replace("## Worked example", wall + "\n\n## Worked example")

    assert any(issue.startswith("wall of text") for issue in assess_answer(answer).issues)


def test_run_on_sentence_is_reported() -> None:
    run_on = "Shear force " + "and then the moment changes " * 12 + "until the end."
    answer = GOOD.replace("## Common mistakes", run_on + "\n\n## Common mistakes")

    assert "run-on sentences" in assess_answer(answer).issues


def test_short_checklist_bullets_are_not_run_on_sentences() -> None:
    bullets = "\n".join(f"- Item {index} without a period" for index in range(30))

    assert "run-on sentences" not in assess_answer(GOOD + "\n" + bullets).issues


@pytest.mark.parametrize(
    "broken",
    [
        GOOD.replace(r"\[", "", 1),
        GOOD.replace(r"\)", "", 1),
        GOOD + "\n$$V = P",
    ],
)
def test_unbalanced_math_is_reported(broken: str) -> None:
    assert "unbalanced math delimiters" in assess_answer(broken).issues


def test_bare_latex_is_reported() -> None:
    answer = GOOD + "\nThe slope is \\frac{dM}{dx} = V."

    assert "LaTeX outside math delimiters" in assess_answer(answer).issues


def test_dollar_math_is_not_bare_latex() -> None:
    answer = GOOD + "\nThe slope is $\\frac{dM}{dx} = V$."

    assert "LaTeX outside math delimiters" not in assess_answer(answer).issues


def test_leftover_hosted_citation_markers_are_reported() -> None:
    answer = GOOD + " \ue200filecite\ue202turn0file3\ue201"

    assert "leftover citation markers" in assess_answer(answer).issues


def test_missing_citations_are_reported() -> None:
    answer = GOOD.replace("[Lecture_07_Shear_and_Moment.pdf]", "").replace(
        "[Tutorial_04_Beams.pdf]", ""
    )

    assert "no inline source citation" in assess_answer(answer).issues


def test_unclosed_code_fence_is_reported() -> None:
    assert "unclosed code fence" in assess_answer(GOOD + "\n```python\nV = 5").issues


def test_too_short_and_too_long_answers_are_reported() -> None:
    assert "too short (4 words)" in assess_answer("Shear force is internal.").issues
    assert any(issue.startswith("too long") for issue in assess_answer(GOOD, max_words=200).issues)


def test_direct_questions_do_not_need_the_explain_layout() -> None:
    answer = (
        "For a cantilever of length \\(L\\) under a uniform load \\(w\\), the **maximum shear "
        "force** occurs at the fixed support [Lecture_07_Shear_and_Moment.pdf]:\n\n"
        "\\[\nV_{\\max} = wL\n\\]\n\n"
        "The shear falls linearly to zero at the free end, because each slice of the beam "
        "carries only the load beyond it. The fixed support must therefore resist the whole "
        "load, which is why the wall reaction equals the total distributed load. Check the "
        "units: \\(w\\) in kN/m times \\(L\\) in m gives kN, a force, as expected for shear."
    )

    quality = assess_answer(answer, expect_sections=False)

    assert quality.issues == []
    assert quality.concepts == []


def test_self_test_questions_are_counted() -> None:
    assert assess_answer(GOOD).practice_questions == 3


def test_explanation_without_self_test_is_reported() -> None:
    start = GOOD.index("## Check yourself")
    end = GOOD.index("## Study checklist")
    issues = assess_answer(GOOD[:start] + GOOD[end:]).issues

    assert "only 0 self-test questions with hidden answers" in issues
    assert "missing sections: Check yourself" in issues


def test_unclosed_hidden_answer_is_reported() -> None:
    answer = GOOD.replace("</details>", "", 1)

    assert "unclosed hidden answer" in assess_answer(answer).issues


def test_unicode_symbol_inside_text_is_reported() -> None:
    answer = GOOD.replace(r"\text{kN}\cdot\text{m}", r"\text{kN·m}")

    assert "Unicode symbol inside \\text{} (KaTeX shows it in red)" in assess_answer(answer).issues


def test_page_numbered_citations_count() -> None:
    from app.services.answer_quality import _INLINE_CITATION

    text = "See [course text.pdf, p. 87] and [Lecture_07.pdf, pp. 3-5] and [notes.txt]."

    assert len(_INLINE_CITATION.findall(text)) == 3
