from app.services.textbook_toc import chapters, describe, parse_contents

# Shaped like the SYDE 212 course text's contents pages after extraction.
BOOK = """[Front matter, PDF page 1]
Introductory Statistics Explained

[Front matter, PDF page 3]
Contents
1 Introduction 1
1.1 Introduction . . . . . . . . . . . . . . . . . . . . . . . . . . 2
1.2 Descriptive Statistics . . . . . . . . . . . . . . . . . . . . . 2
2 Gathering Data 7
2.1 Introduction . . . . . . . . . . . . . . . . . . . . . . . . . . 9
2.3 Types of Sampling . . . . . . . . . . . . . . . . . . . . . . . 10
2.3.1 Simple Random Sampling . . . . . . . . . . . . . . . . . 11
3 Descriptive Statistics 21
3.3 Numerical Measures . . . . . . . . . . . . . . . . . . . . . . 32
3.3.2 Measures of Central Tendency . . . . . . . . . . . . . . . 34
i

[Front matter, PDF page 4]
Balka ISE 1.10 CONTENTS ii
4 Probability 59
4.5 Bayes Theorem . . . . . . . . . . . . . . . . . . . . . . . . . 82
5 Discrete Random Variables and Discrete Probability Distribu-
tion 97
5.1 Introduction . . . . . . . . . . . . . . . . . . . . . . . . . . 99

[Page 1]
Chapter 1
Introduction
""" + "\n".join(f"body line {n}" for n in range(60))


def test_contents_entries_are_read_across_pages_and_wrapped_titles() -> None:
    entries = parse_contents(BOOK)

    assert [entry.number for entry in entries[:3]] == ["1", "1.1", "1.2"]
    assert ("3.3.2", "Measures of Central Tendency", 34) in [
        (entry.number, entry.title, entry.page) for entry in entries
    ]
    assert ("5", "Discrete Random Variables and Discrete Probability Distribution", 97) in [
        (entry.number, entry.title, entry.page) for entry in entries
    ]


def test_chapters_have_page_ranges_and_top_level_sections() -> None:
    found = {chapter.number: chapter for chapter in chapters(parse_contents(BOOK))}

    assert sorted(found) == [1, 2, 3, 4, 5]
    three = found[3]
    assert (three.title, three.first_page, three.last_page) == ("Descriptive Statistics", 21, 58)
    assert three.sections == ["3.3 Numerical Measures"]
    assert found[5].last_page is None
    assert describe(three) == (
        "Chapter 3: Descriptive Statistics (pp. 21-58): 3.3 Numerical Measures"
    )


def test_documents_without_a_contents_page_have_no_chapters() -> None:
    slides = "Lecture 3\nToday: sampling\n1 Why sample 4\n2 Bias 5"

    assert parse_contents(slides) == []
    assert chapters(parse_contents("Contents\n1 Only one chapter 1\n")) == []


def test_pdf_ligatures_in_titles_become_plain_letters() -> None:
    ligature = "ﬁ"  # the single "fi" character PDF text often contains
    text = f"Contents\n7 Sampling 175\n8 Con{ligature}dence Intervals 191\n9 Hypothesis Tests 223\n"

    titles = [chapter.title for chapter in chapters(parse_contents(text))]

    assert titles[1] == "Confidence Intervals"
